{{/*
Expand the name of the chart.
*/}}
{{- define "orchestack.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "orchestack.fullname" -}}
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
{{- define "orchestack.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "orchestack.labels" -}}
helm.sh/chart: {{ include "orchestack.chart" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: orchestack
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}

{{/*
Service labels
*/}}
{{- define "orchestack.serviceLabels" -}}
{{ include "orchestack.labels" . }}
app.kubernetes.io/name: {{ .serviceName }}
app.kubernetes.io/instance: {{ .Release.Name }}-{{ .serviceName }}
app.kubernetes.io/component: {{ .component | default "service" }}
{{- end }}

{{/*
Common environment variables for all services
*/}}
{{- define "orchestack.commonEnv" -}}
- name: NATS_URL
  value: {{ printf "nats://%s-nats:4222" .Release.Name }}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "orchestack.fullname" . }}-db
      key: url
- name: MINIO_ENDPOINT
  value: {{ printf "http://%s-minio:9000" .Release.Name }}
- name: MINIO_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "orchestack.fullname" . }}-minio
      key: access-key
- name: MINIO_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "orchestack.fullname" . }}-minio
      key: secret-key
- name: VAULT_ADDR
  value: {{ .Values.vault.externalAddr | default (printf "http://%s-vault:8200" .Release.Name) }}
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: {{ printf "http://%s-otel-collector:4317" .Release.Name }}
{{- end }}

{{/*
Security context for OpenShift compatibility
*/}}
{{- define "orchestack.securityContext" -}}
runAsNonRoot: true
{{- if not .Values.openshift.enabled }}
runAsUser: 65534
runAsGroup: 65534
fsGroup: 65534
{{- end }}
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{/*
Container security context
*/}}
{{- define "orchestack.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop:
    - ALL
{{- end }}
