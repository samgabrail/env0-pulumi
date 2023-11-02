import json
import pulumi
from pulumi_aws import ec2, iam, eks

# Define vars
config = pulumi.Config()
cluster_name = config.require("cluster_name")
cluster_version = config.require("cluster_version")
instance_type = config.require("instance_type")
cluster_min_size = config.require_int("cluster_min_size")
cluster_max_size = config.require_int("cluster_max_size")
cluster_desired_size = config.require_int("cluster_desired_size")
private_subnets_str = config.require("private_subnets")
availability_zones_str = config.require("availability_zones")
private_subnets = json.loads(private_subnets_str)
availability_zones = json.loads(availability_zones_str)

# Using Pulumi logging for cleaner debug output
pulumi.log.info(
    f"These are the private subnets: {private_subnets}, {type(private_subnets)}")
pulumi.log.info(f"These are the availability zones: {availability_zones}")


# Define IAM Role
iam_role = iam.Role("eks-node-role",
                    assume_role_policy=pulumi.Output.from_input({
                        "Version": "2012-10-17",
                        "Statement": [{
                            "Action": "sts:AssumeRole",
                            "Principal": {
                                "Service": "eks.amazonaws.com",
                            },
                            "Effect": "Allow",
                        }],
                    }))

iam_role_policy_attachment = iam.RolePolicyAttachment("eks-AmazonEKSClusterPolicy",
                                                      policy_arn="arn:aws:iam::aws:policy/AmazonEKSClusterPolicy",
                                                      role=iam_role.name)

# Create a VPC
vpc = ec2.Vpc(
    "myVpc",
    cidr_block="10.0.0.0/16",
    enable_dns_hostnames=True,
    tags={
        "Name": "myVpc",
        f"kubernetes.io/cluster/{cluster_name}": "shared",
    },
)

# Create private subnets
private_subnet_ids = []
for i in range(len(private_subnets)):
    pulumi.log.info(f"cidr block: {private_subnets[i]}")
    subnet = ec2.Subnet(
        f"privateSubnet{i + 1}",
        cidr_block=private_subnets[i],
        vpc_id=vpc.id,
        availability_zone=availability_zones[i],
        tags={
            "Name": f"privateSubnet{i + 1}",
            f"kubernetes.io/cluster/{cluster_name}": "shared",
            "kubernetes.io/role/internal-elb": "1",
        },
    )
    private_subnet_ids.append(subnet.id)

# Create an EKS cluster security group
eks_cluster_sg = ec2.SecurityGroup('eks-cluster-sg',
                                   vpc_id=vpc.id,
                                   description='EKS cluster security group',
                                   tags={
                                       "Name": "eks-cluster-sg",
                                       f"kubernetes.io/cluster/{cluster_name}": "owned",
                                   })

# Create a security group for worker nodes
nodegroup_sg = ec2.SecurityGroup('nodegroup-sg',
                                 vpc_id=vpc.id,
                                 description='Worker node security group',
                                 tags={
                                     "Name": "nodegroup-sg",
                                     f"kubernetes.io/cluster/{cluster_name}": "owned",
                                 })

# Allow inbound communication from the control plane to the worker nodes
eks_cluster_sg_rule = ec2.SecurityGroupRule('eks-cluster-sg-rule',
                                            type="ingress",
                                            from_port=1025,
                                            to_port=65535,
                                            protocol="tcp",
                                            security_group_id=nodegroup_sg.id,
                                            source_security_group_id=eks_cluster_sg.id)

# Allow outbound communication from the worker nodes to the control plane
nodegroup_sg_rule = ec2.SecurityGroupRule('nodegroup-ingress',
                                          type='ingress',
                                          from_port=0,
                                          to_port=65535,
                                          protocol='tcp',
                                          security_group_id=nodegroup_sg.id,  # Attach the rule to the node group's SG
                                          # Allowing traffic from itself, adjust as necessary
                                          source_security_group_id=nodegroup_sg.id,
                                          description='Allow node to node communication within the same SG')

# Create an EKS cluster
eks_cluster = eks.Cluster(cluster_name,
                          role_arn=iam_role.arn,
                          vpc_config=eks.ClusterVpcConfigArgs(
                              subnet_ids=private_subnet_ids,
                              security_group_ids=[eks_cluster_sg.id]
                          ),
                          version=cluster_version,
                          )


# Deploy EBS CSI driver as a Kubernetes add-on
# ebs_csi = eks.Addon('ebs-csi-addon',
#                     cluster_name=eks_cluster.name,
#                     addon_name='aws-ebs-csi-driver',
#                     addon_version='v1.19.0-eksbuild.2')


nodegroup_role = iam.Role("eks-nodegroup-role",
                          assume_role_policy=pulumi.Output.from_input({
                              "Version": "2012-10-17",
                              "Statement": [{
                                  "Action": "sts:AssumeRole",
                                  "Principal": {
                                      "Service": "ec2.amazonaws.com",
                                  },
                                  "Effect": "Allow",
                              }],
                          }))

# List of policies to attach
policies_to_attach = [
    "AmazonEKSWorkerNodePolicy",
    "AmazonEC2ContainerRegistryReadOnly",
    "AmazonEKS_CNI_Policy"
]

# Loop through the policies and attach each to the role
for policy in policies_to_attach:
    iam.RolePolicyAttachment(f"eks-{policy}",
                             policy_arn=f"arn:aws:iam::aws:policy/{policy}",
                             role=nodegroup_role.name)


launch_template = ec2.LaunchTemplate("nodegroup-launch-template",
                                     instance_type=instance_type,
                                     description="Launch Template for EKS Node Group",
                                     vpc_security_group_ids=[nodegroup_sg.id]
                                     )


nodegroup = eks.NodeGroup("eks-nodegroup",
                          cluster_name=eks_cluster.name,
                          node_role_arn=nodegroup_role.arn,
                          subnet_ids=private_subnet_ids,
                          scaling_config=eks.NodeGroupScalingConfigArgs(
                              desired_size=cluster_desired_size,
                              min_size=cluster_min_size,
                              max_size=cluster_max_size,
                          ),
                          launch_template={
                              "id": launch_template.id,
                              "version": launch_template.latest_version,
                          })


pulumi.export("ClusterEndpoint", eks_cluster.endpoint)
pulumi.export("ClusterName",
              eks_cluster.name)
