# Azure setup for project storage

Project folders and job outputs are saved to Azure Blob Storage. The connection string and the app's
client secret are kept in Azure Key Vault. This page records what was provisioned, how to check it, and
what is still missing. It holds no secret values.

## Resources

| Resource | Name | Where |
|---|---|---|
| Resource group | `deliverypilot-rg` | existing, uksouth |
| Storage account | `dprevanyvideo` | uksouth, Standard_LRS, TLS 1.2 minimum, public blob access off |
| Blob container | `reverse-any-video` | private. One folder per project under `projects/<slug>/` |
| Key Vault | `dp-kv-deliverypilot` | existing, access policies (not RBAC) |
| Key Vault secret | `reverse-any-video-storage-connection-string` | storage connection string |
| Key Vault secret | `reverse-any-video-app-client-secret` | client secret of the app's service principal |
| Service principal | `reverse-any-video-app` | Storage Blob Data Contributor on `dprevanyvideo` only |
| Key Vault access | `reverse-any-video-app` | `get`, `list` on secrets |
| Fly app | `reverse-any-video` | secrets `AZURE_KEYVAULT_URL`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` |

Layout inside the container:

```
reverse-any-video/
  projects/<slug>/project.json
  projects/<slug>/jobs/<job_id>/script.md, SKILL.md, analysis.json, report.html
```

## How the app reads its settings

`storage.py` gets the connection string in this order:

1. `AZURE_STORAGE_CONNECTION_STRING`, if set (local runs only).
2. Otherwise, Key Vault at `AZURE_KEYVAULT_URL`, secret `AZURE_STORAGE_SECRET_NAME`
   (default `reverse-any-video-storage-connection-string`), read with the service principal
   `AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET`.

## Status

Checked 2026-11-22 against the `info@deliverypilot.net` login:

| Step | State |
|---|---|
| Storage account `dprevanyvideo` | done (Succeeded, uksouth) |
| Container `reverse-any-video` | done |
| Connection string in Key Vault | done |
| Service principal and Blob Data Contributor role | done |
| Client secret in Key Vault | done |
| Key Vault `get`/`list` for the principal | done |
| Fly secrets on `reverse-any-video` | done (staged, then deployed) |
| Code deployed to Fly with project endpoints | done. The first deploy crashed because the Dockerfile did not copy `storage.py`. Fixed. |
| `/healthz` reports `azure_storage: true` | done |
| `GET /api/projects` reads from Azure | done (empty list, HTTP 200) |
| `ACCESS_TOKEN` on Fly | **not set.** Anyone with the URL can create projects and start jobs. Set it before sharing. |

Read-only check on the live app, 2026-11-22: `/healthz` returns `azure_storage: true`, and `GET /api/projects` returns `{"projects": []}` with HTTP 200.

## Verify

```bash
az account show --query user.name -o tsv                              # info@deliverypilot.net
az storage account show -n dprevanyvideo -g deliverypilot-rg --query provisioningState -o tsv   # Succeeded
az storage container list --account-name dprevanyvideo --auth-mode login --query "[].name" -o tsv  # reverse-any-video
az keyvault secret list --vault-name dp-kv-deliverypilot --query "[?contains(name,'reverse-any-video')].name" -o tsv
fly secrets list --app reverse-any-video                              # needs the four AZURE_* names
curl -s https://reverse-any-video.fly.dev/healthz | python3 -m json.tool   # azure_storage: true once set
```

## Finish the Fly secrets

Only the last step is missing. Run it from a shell logged in to the same account. The client secret is
read from Key Vault and never printed:

```bash
KV=dp-kv-deliverypilot; APPID=$(az ad sp list --display-name reverse-any-video-app --query "[0].appId" -o tsv); TENANT=$(az account show --query tenantId -o tsv); fly secrets set AZURE_KEYVAULT_URL=https://$KV.vault.azure.net/ AZURE_TENANT_ID=$TENANT AZURE_CLIENT_ID=$APPID AZURE_CLIENT_SECRET="$(az keyvault secret show --vault-name $KV --name reverse-any-video-app-client-secret --query value -o tsv)" --app reverse-any-video
```

Setting secrets restarts the running machine on the current image, which is harmless. The new code still
needs a deploy (`fly deploy --ha=false`).

## Rotate or remove

- Rotate the client secret: `az ad sp credential reset --id <appId>`, then store the new password in
  `reverse-any-video-app-client-secret` and set the Fly secret again.
- Remove everything: delete the service principal, the Key Vault secrets, the container and the storage
  account. Then `fly secrets unset AZURE_KEYVAULT_URL AZURE_TENANT_ID AZURE_CLIENT_ID AZURE_CLIENT_SECRET --app reverse-any-video`.
