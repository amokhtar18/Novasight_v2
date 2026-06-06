{{/*
Helpers for the NovaSight chart. Nothing here encodes infrastructure values — only
naming, labels, and the effective-config assembly (which reads from .Values).
*/}}

{{- define "novasight.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "novasight.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "novasight.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Common labels applied to every object. */}}
{{- define "novasight.labels" -}}
helm.sh/chart: {{ include "novasight.chart" . }}
app.kubernetes.io/name: {{ include "novasight.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: novasight
{{- end -}}

{{/* Selector labels for a component. Call: include "novasight.selectorLabels" (dict "ctx" . "component" "api") */}}
{{- define "novasight.selectorLabels" -}}
app.kubernetes.io/name: {{ include "novasight.name" .ctx }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "novasight.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "novasight.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* Names of the bundled dependency Services (used by computed config defaults). */}}
{{- define "novasight.postgresql.fullname" -}}{{ printf "%s-postgresql" (include "novasight.fullname" .) }}{{- end -}}
{{- define "novasight.redis.fullname" -}}{{ printf "%s-redis" (include "novasight.fullname" .) }}{{- end -}}
{{- define "novasight.minio.fullname" -}}{{ printf "%s-minio" (include "novasight.fullname" .) }}{{- end -}}
{{- define "novasight.clickhouse.fullname" -}}{{ printf "%s-clickhouse" (include "novasight.fullname" .) }}{{- end -}}

{{/*
Effective non-secret config (env vars). Starts from connection defaults for any
ENABLED bundled dependency (so the app reaches them by in-cluster Service DNS), then
overlays .Values.config — which always wins. External (cloud) deployments simply
leave the deps disabled and supply the real endpoints in .Values.config.
Returns a YAML-serializable dict; callers `toYaml` it.
*/}}
{{- define "novasight.effectiveConfig" -}}
{{- $defaults := dict -}}
{{- if .Values.postgresql.enabled -}}
  {{- $_ := set $defaults "POSTGRES__HOST" (include "novasight.postgresql.fullname" .) -}}
  {{- $_ := set $defaults "POSTGRES__PORT" "5432" -}}
{{- end -}}
{{- if .Values.redis.enabled -}}
  {{- $_ := set $defaults "REDIS__HOST" (include "novasight.redis.fullname" .) -}}
  {{- $_ := set $defaults "REDIS__PORT" "6379" -}}
{{- end -}}
{{- if .Values.minio.enabled -}}
  {{- $_ := set $defaults "OBJECT_STORE__ENDPOINT_URL" (printf "http://%s:9000" (include "novasight.minio.fullname" .)) -}}
{{- end -}}
{{- if .Values.clickhouse.enabled -}}
  {{- $_ := set $defaults "CLICKHOUSE__HOST" (include "novasight.clickhouse.fullname" .) -}}
  {{- $_ := set $defaults "CLICKHOUSE__PORT" "8123" -}}
{{- end -}}
{{- $config := mustMergeOverwrite $defaults (.Values.config | default dict) -}}
{{- toYaml $config -}}
{{- end -}}

{{/* Name of the ConfigMap and Secret holding the application environment. */}}
{{- define "novasight.configMapName" -}}{{ printf "%s-config" (include "novasight.fullname" .) }}{{- end -}}
{{- define "novasight.secretName" -}}{{ printf "%s-secret" (include "novasight.fullname" .) }}{{- end -}}

{{/*
envFrom block shared by every application workload: the non-secret ConfigMap plus the
Secret. This is the ONLY way config reaches the app — golden rule 1.
*/}}
{{- define "novasight.envFrom" -}}
- configMapRef:
    name: {{ include "novasight.configMapName" . }}
- secretRef:
    name: {{ include "novasight.secretName" . }}
{{- end -}}

{{/* Resolve an image ref: images.<key>.repository:(tag|AppVersion). */}}
{{- define "novasight.image" -}}
{{- $img := index .ctx.Values.images .key -}}
{{- $tag := $img.tag | default .ctx.Chart.AppVersion -}}
{{- printf "%s:%s" $img.repository $tag -}}
{{- end -}}
