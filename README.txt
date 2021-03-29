# scheduled-events-operator-2

Avoid the hassle when Azure maintains one of the nodes in your Azure Kubernetes Service cluster.
This is a program written in python, installed as a deamonset in your AKS cluster, that will take care of that.

## not a short story about what this is about and what it's used for

Azure does VM maintenance from time to time and lets you know a little bit in advance via scheduled events.
https://docs.microsoft.com/en-us/azure/virtual-machines/linux/scheduled-events

This listens for scheduled events. It then takes automatic action to avoid service downtime.
If a scheduled event occurs, it automatically drain the node in preparation for maintenance.
The node becomes empty, so no maintenance operations on it can harm your service.
The node will become useful again after a period of time, or it will soon be removed by the cluster's autoscaler.

For this to work, your cluster&application must respond correctly to a node drain operation.
In particular, you need: a working graceful shutdown, PodDisruptionBudget policy.

The program works in a painfully simple way, it has dependencies on several external programs (kubectl, jq).
Docker image size is under 50 MB, python and dependencies take up some disk space.

## how to build and run this

Deployment can be done in a standard way.
Assume that "todayisnotmonday" is your Azure Container Registry.
The deployment for AKS+helm is as follows:

$ ./build.sh --no-cache
$ docker tag seo2:1.0.0 todayisnotmonday.azurecr.io/seo2:1.0.0
$ docker push todayisnotmonday.azurecr.io/seo2:1.0.0
$ helm install seo2 charts/seo2 --set namespace=seo2,namespaceCreate=true --set image.repository=todayisnotmonday.azurecr.io/seo2
