import pulumi
from pulumi import Output
from pulumi_aws import ec2, iam, eks

# Define vars
config = pulumi.Config()
cluster_name = config.require("cluster_name")
cluster_version = config.require("cluster_version")
instance_types = list(config.require("instance_types"))
cluster_min_size = config.require_int("cluster_min_size")
cluster_max_size = config.require_int("cluster_max_size")
cluster_desired_size = config.require_int("cluster_desired_size")

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

# Create public and private subnets
public_subnet = ec2.Subnet(
    "publicSubnet",
    cidr_block="10.0.1.0/24",
    vpc_id=vpc.id,
    tags={
        "Name": "publicSubnet",
        f"kubernetes.io/cluster/{cluster_name}": "shared",
        "kubernetes.io/role/elb": "1",
    },
)

private_subnet = ec2.Subnet(
    "privateSubnet",
    cidr_block="10.0.2.0/24",
    vpc_id=vpc.id,
    tags={
        "Name": "privateSubnet",
        f"kubernetes.io/cluster/{cluster_name}": "shared",
        "kubernetes.io/role/internal-elb": "1",
    },
)


# Create an EKS cluster
eks_cluster = eks.Cluster(cluster_name,
                          role_arn=iam_role.arn,
                          vpc_config=eks.ClusterVpcConfigArgs(
                              subnet_ids=[public_subnet.id, private_subnet.id]
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

nodegroup_role_policy_attachment = iam.RolePolicyAttachment("eks-AmazonEKSWorkerNodePolicy",
    policy_arn="arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    role=nodegroup_role.name)


nodegroup = eks.NodeGroup("eks-nodegroup",
    cluster_name=eks_cluster.name,
    node_role_arn=nodegroup_role.arn,
    subnet_ids=[public_subnet.id, private_subnet.id],
    scaling_config=eks.NodeGroupScalingConfigArgs(
        desired_size=cluster_desired_size,
        min_size=cluster_min_size,
        max_size=cluster_max_size,
    ),
    instance_types=instance_types,
    ami_type="AL2_x86_64",
)


pulumi.export("Cluster Endpoint", eks_cluster.endpoint)
pulumi.export("kubeconfig-certificate-authority-data", eks_cluster.certificate_authority.data)
