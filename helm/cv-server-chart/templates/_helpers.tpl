{{/* Labels on every object of the release. */}}
{{- define "cv-server.labels" -}}
app: cv-server
app.kubernetes.io/name: cv-server
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Values.image.tag | trunc 12 | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* Selector labels. Immutable on a Deployment: never change them. */}}
{{- define "cv-server.selectorLabels" -}}
app: cv-server
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "cv-server.fullname" -}}
{{ .Release.Name }}-cv-server
{{- end -}}

{{- define "cv-server.image" -}}
{{ printf "%s:%s" .Values.image.repository .Values.image.tag }}
{{- end -}}

{{/* Pod-level security context that meets the "restricted" Pod Security Standard. */}}
{{- define "cv-server.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 1000
runAsGroup: 1000
fsGroup: 1000
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "cv-server.containerSecurityContext" -}}
allowPrivilegeEscalation: false
# The container never writes to its own image; scratch space is /tmp (emptyDir).
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}

{{/* True when the release always keeps at least two pods. */}}
{{- define "cv-server.multiReplica" -}}
{{- if .Values.autoscaling.enabled -}}
{{- if ge (int .Values.autoscaling.minReplicas) 2 -}}true{{- end -}}
{{- else if ge (int .Values.replicaCount) 2 -}}true{{- end -}}
{{- end -}}
