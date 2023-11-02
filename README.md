# Overview
This is a simple demo to explain Pulumi and how it can be used to provision AWS resources using Python.

## Pulumi

### Installing Pulumi

```bash
curl -fsSL https://get.pulumi.com | sh -s -- --version 3.91.1
```

### Getting Started with Pulumi New

Run the following command:

```bash
mkdir Pulumi
cd Pulumi
pulumi new
```

```bash
export AWS_ACCESS_KEY_ID=your-access-key-id
export AWS_SECRET_ACCESS_KEY=your-secret-access-key
pulumi up
```

To get the kubeconfig for the EKS cluster:

```bash
aws eks update-kubeconfig --name $(pulumi stack output ClusterName)
```

Now run kubectl commands to interact with the EKS cluster:

```bash
kubectl get nodes
```