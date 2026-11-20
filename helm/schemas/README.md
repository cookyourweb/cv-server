# CRD schemas for kubeconform

kubeconform only knows built-in Kubernetes kinds. These two files let CI validate the
chart's `SecretStore` and `ExternalSecret` strictly instead of skipping them.

| File | Source |
|---|---|
| `secretstore_v1.json` | `openAPIV3Schema` of the `SecretStore` CRD, version `v1`, External Secrets chart **2.15.0** |
| `externalsecret_v1.json` | `openAPIV3Schema` of the `ExternalSecret` CRD, version `v1`, same chart |

They must match the ESO version pinned in `infra/k8s/platform/versions.env`. When that
version changes, regenerate them: `helm template` the new chart and copy each CRD's
`spec.versions[name=v1].schema.openAPIV3Schema` to the matching file.
