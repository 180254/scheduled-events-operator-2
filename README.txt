# scheduled-events-operator-2

The application responds to scheduled events for virtual machines on the Azure platform by draining AKS nodes.

## advertising slogan

Avoid the hassle when Azure maintains one of the nodes in your Azure Kubernetes Service cluster.
This program takes care of that. The program is written in python and is installable as a daemon in the AKS cluster.

## a longer story about what it's about and what it's for

Azure does VM maintenance from time to time and notifies you some time in advance using scheduled events.
https://docs.microsoft.com/en-us/azure/virtual-machines/linux/scheduled-events

The program listens for scheduled events. It then takes automatic action to avoid service downtime.
If a scheduled event occurs, it automatically drains the node in preparation for maintenance.
The node becomes empty so that no maintenance operations can harm your service.
The node will become serviceable again after some time, or the cluster's autoscaler will soon remove it.

Your cluster and application must respond correctly to a node drain operation for this to work.
In particular, you need a working application graceful shutdown, PodDisruptionBudget policy.

The program works in a painfully simple way, has dependencies on several external programs (kubectl).
Docker image size is under 100 MB, python and dependencies take up some disk space.

## building and running

You can do the deployment the standard way.
Assume that "todayisnotmonday" is your Azure Container Registry.
The deployment for AKS+helm is as follows:

$ ./build.sh --no-cache
$ docker tag seo2:1.0.0 todayisnotmonday.azurecr.io/seo2:1.0.0
$ docker push todayisnotmonday.azurecr.io/seo2:1.0.0
$ helm install seo2 charts/seo2 --set namespace=seo2,namespaceCreate=true --set image.repository=todayisnotmonday.azurecr.io/seo2
