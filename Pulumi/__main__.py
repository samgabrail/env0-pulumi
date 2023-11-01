import json
import pulumi
from pulumi import Output
from pulumi_aws import ec2, iam, eks

# Define vars
config = pulumi.Config()
cluster_name = config.require("cluster_name")
cluster_version = config.require("cluster_version")
instance_types_str = config.require("instance_types")
cluster_min_size = config.require_int("cluster_min_size")
cluster_max_size = config.require_int("cluster_max_size")
cluster_desired_size = config.require_int("cluster_desired_size")
private_subnets_str = config.require("private_subnets")
availability_zones_str = config.require("availability_zones")
private_subnets = json.loads(private_subnets_str)
availability_zones = json.loads(availability_zones_str)
instance_types = json.loads(instance_types_str)

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


# Create an EKS cluster
eks_cluster = eks.Cluster(cluster_name,
                          role_arn=iam_role.arn,
                          vpc_config=eks.ClusterVpcConfigArgs(
                              subnet_ids=private_subnet_ids
                          ),
                          version=cluster_version,
                          )


# Deploy EBS CSI driver as a Kubernetes add-on
ebs_csi = eks.Addon('ebs-csi-addon',
                    cluster_name=eks_cluster.name,
                    addon_name='aws-ebs-csi-driver',
                    addon_version='v1.19.0-eksbuild.2')


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

nodegroup = eks.NodeGroup("eks-nodegroup",
                          cluster_name=eks_cluster.name,
                          node_role_arn=nodegroup_role.arn,
                          subnet_ids=private_subnet_ids,
                          scaling_config=eks.NodeGroupScalingConfigArgs(
                              desired_size=cluster_desired_size,
                              min_size=cluster_min_size,
                              max_size=cluster_max_size,
                          ),
                          instance_types=instance_types,
                          ami_type="AL2_x86_64",
                          )


pulumi.export("ClusterEndpoint", eks_cluster.endpoint)
pulumi.export("ClusterName",
              eks_cluster.name)
