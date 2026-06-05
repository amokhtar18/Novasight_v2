{{/*
Helpers for the Analytica chart. Nothing here encodes infrastructure values — only
naming, labels, and the effective-config assembly (which reads from .Values).
*/}}

{{- define "analytica.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "analytica.fullname" -}}
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

{{- define "analytica.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Common labels applied to every object. */}}
{{- define "analytica.labels" -}}
helm.sh/chart: {{ include "analytica.chart" . }}
app.kubernetes.io/name: {{ include "analytica.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: analytica
{{- end -}}

{{/* Selector labels for a component. Call: include "analytica.selectorLabels" (dict "ctx" . "component" "api") */}}
{{- define "analytica.selectorLabels" -}}
app.kubernetes.io/name: {{ include "analytica.name" .ctx }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "analytica.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "analytica.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* Names of the bundled dependency Services (used by computed config defaults). */}}
{{- define "analytica.postgresql.fullname" -}}{{ printf "%s-postgresql" (include "analytica.fullname" .) }}{{- end -}}
{{- define "analytica.redis.fullname" -}}{{ printf "%s-redis" (include "analytica.fullname" .) }}{{- end -}}
{{- define "analytica.minio.fullname" -}}{{ printf "%s-minio" (include "analytica.fullname" .) }}{{- end -}}
{{- define "analytica.clickhouse.fullname" -}}{{ printf "%s-clickhouse" (include "analytica.fullname" .) }}{{- end -}}

{{/*
Effective non-secret config (env vars). Starts from connection defaults for any
ENABLED bundled dependency (so the app reaches them by in-cluster Service DNS), then
overlays .Values.config — which always wins. External (cloud) deployments simply
leave the deps disabled and supply the real endpoints in .Values.config.
Returns a YAML-serializable dict; callers `toYaml` it.
*/}}
{{- define "analytica.effectiveConfig" -}}
{{- $defaults := dict -}}
{{- if .Values.postgresql.enabled -}}
  {{- $_ := set $defaults "POSTGRES__HOST" (include "analytica.postgresql.fullname" .) -}}
  {{- $_ := set $defaults "POSTGRES__PORT" "5432" -}}
{{- end -}}
{{- if .Values.redis.enabled -}}
  {{- $_ := set $defaults "REDIS__HOST" (include "analytica.redis.fullname" .) -}}
  {{- $_ := set $defaults "REDIS__PORT" "6379" -}}
{{- end -}}
{{- if .Values.minio.enabled -}}
  {{- $_ := set $defaults "OBJECT_STORE__ENDPOINT_URL" (printf "http://%s:9000" (include "analytica.minio.fullname" .)) -}}
{{- end -}}
{{- if .Values.clickhouse.enabled -}}
  {{- $_ := set $defaults "CLICKHOUSE__HOST" (include "analytica.clickhouse.fullname" .) -}}
  {{- $_ := set $defaults "CLICKHOUSE__PORT" "8123" -}}
{{- end -}}
{{- $config := mustMergeOverwrite $defaults (.Values.config | default dict) -}}
{{- toYaml $config -}}
{{- end -}}

{{/* Name of the ConfigMap and Secret holding the application environment. */}}
{{- define "analytica.configMapName" -}}{{ printf "%s-config" (include "analytica.fullname" .) }}{{- end -}}
{{- define "analytica.secretName" -}}{{ printf "%s-secret" (include "analytica.fullname" .) }}{{- end -}}

{{/*
envFrom block shared by every application workload: the non-secret ConfigMap plus the
Secret. This is the ONLY way config reaches the app — golden rule 1.
*/}}
{{- define "analytica.envFrom" -}}
- configMapRef:
    name: {{ include "analytica.configMapName" . }}
- secretRef:
    name: {{ include "analytica.secretName" . }}
{{- end -}}

{{/* Resolve an image ref: images.<key>.repository:(tag|AppVersion). */}}
{{- define "analytica.image" -}}
{{- $img := index .ctx.Values.images .key -}}
{{- $tag := $img.tag | default .ctx.Chart.AppVersion -}}
{{- printf "%s:%s" $img.repository $tag -}}
{{- end -}}
