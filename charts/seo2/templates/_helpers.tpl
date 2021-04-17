{{/*
Expand the name of the chart.
*/}}
{{- define "seo2.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "seo2.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "seo2.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Expand the namespace of the chart.
*/}}
{{- define "seo2.namespace" -}}
{{- default .Release.Namespace .Values.namespace  -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "seo2.labels" -}}
helm.sh/chart: {{ include "seo2.chart" . }}
{{ include "seo2.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "seo2.selectorLabels" -}}
app.kubernetes.io/name: {{ include "seo2.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "seo2.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (printf "%s-%s" (include "seo2.fullname" .) "serviceaccount" | trunc 63 | trimSuffix "-") .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the name of the cluster role to use
*/}}
{{- define "seo2.clusterRoleName" -}}
{{- printf "%s-%s" (include "seo2.fullname" .) "clusterrole" | trunc 63 | trimSuffix "-" -}}
{{- end }}


{{/*
Create the name of the cluster role binding to use
*/}}
{{- define "seo2.clusterRoleBindingName" -}}
{{- printf "%s-%s" (include "seo2.fullname" .) "clusterrolebinding" | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{/*
Create the name of the configmap to use
*/}}
{{- define "seo2.configMapName" -}}
{{- printf "%s-%s" (include "seo2.fullname" .) "configmap" | trunc 63 | trimSuffix "-" -}}
{{- end -}}
