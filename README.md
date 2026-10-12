# OCI Base Database: 19c to 26ai

This repository provides a manually dispatched GitHub Actions workflow using the OCI control-plane API through OCI CLI. It is a deployment template, not an upgrade already executed in your tenancy. Configure and rehearse it on a restored test database first.

## Scope and prerequisites

Oracle supports 19c → 26ai. Its documented prerequisites include OL8, GI 26ai, ARCHIVELOG and flashback. Schedule downtime. Data Guard requires standby-first orchestration; this template rejects detected Data Guard configurations. Non-CDB conversion and OS/GI upgrades are separate preparation tasks. See [Oracle's Base Database upgrade procedure](https://docs.oracle.com/en/cloud/paas/base-database/upgrade-db/).

Prepared for `jibin-panicker/DBUpgrade`. This template supports a CDB on a single-node Base Database VM DB system without Data Guard, subject to OCI precheck and your DBA's approval. It rejects multi-node systems. It does not automate OS/GI preparation, backup creation, application shutdown, SQL acceptance, or recovery. Manual Data Guard configurations may not appear in the association API and must be ruled out by the DBA.

## Install in GitHub

1. Copy this directory's contents, including `.github`, into your repository root and commit to its default branch. No password needs to be sent to an assistant. Use your normal GitHub sign-in or locally authenticated GitHub CLI to publish.
2. Create an isolated Linux GitHub self-hosted runner on an OCI Compute instance, **not on the database host**. Assign labels `self-hosted`, `linux`, `oci-db-maintenance`. Install Python 3.9+ and OCI CLI 3.94.2 in its PATH. The runner needs outbound HTTPS to GitHub and OCI endpoints and access to OCI instance metadata. It does not need SQL network access for this workflow.
3. Restrict the runner to this trusted repository/workflow. Do not expose the privileged runner to untrusted pull requests. Protect the default branch and require review of workflow/script changes.
4. Assign the runner instance to an OCI dynamic group and grant compartment-scoped permissions for database inspection, upgrade/precheck, database homes, DB systems, versions, Data Guard inspection and backup reads. Ask your OCI administrator to tailor policy to the target compartment. This workflow uses `instance_principal`; it stores no OCI API private key in GitHub. See [OCI instance principals](https://docs.oracle.com/en-us/iaas/Content/Identity/Tasks/callingservicesfrominstances.htm).
5. Create environments named **oci-db-precheck** and **oci-db-upgrade**. Configure required reviewers, prevent self-review and restrict deployment to the default branch. YAML referencing an environment does **not** configure approval rules. Confirm your GitHub plan supports these rules for your repository visibility before enabling execution. See [GitHub environment configuration](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).
6. Set these variables identically in both environments. Use one repository for one database; this keeps the concurrency lock unambiguous.

| Environment variable | Value |
| --- | --- |
| `OCI_REGION` | Target region, e.g. `ap-mumbai-1` |
| `OCI_DATABASE_ID` | Source database OCID |
| `OCI_DB_SYSTEM_ID` | Its Base Database DB system OCID |
| `OCI_APPROVED_26AI_VERSION` | Exact available version approved by your DBA; populate after discovery |
| `OCI_26AI_READINESS_CONFIRMED` | Initially `false`; set `true` only after the checklist below |

The runner's instance principal is privileged independently of GitHub environment protection. Runner isolation and repository write controls are essential to the approval boundary.

## Run sequence

1. Open Actions → **OCI Base Database 19c to 26ai** → Run workflow, on the default branch. Select `discover`. Read the available upgrade version identifiers in the log. The workflow obtains candidates from [OCI ListDbVersions](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/db/version/list.html).
2. Have the DBA identify the 26ai release in the OCI Console and record its exact identifier as `OCI_APPROVED_26AI_VERSION` in both environments. Do not invent `26.0.0.0` or choose a version just because it starts with `23`. Marketing release names and underlying version numbers can differ.
3. Complete the readiness checklist and set the readiness variable to `true` in both environments. Run `precheck` with the exact target version. Resolve all reported issues before continuing.
4. Start the maintenance window, stop application writes and scheduled jobs, disable automatic backups, and create an on-demand FULL backup in OCI. Wait for successful completion and save its backup OCID. This implementation deliberately requires a full backup completed within 24 hours; other backup arrangements need adaptation.
5. Run `upgrade` with that same version, backup OCID, and confirmation `UPGRADE <database-OCID>`. The environment reviewer checks the target, maintenance window and recovery evidence before approving. A fresh precheck runs again before the upgrade submission.
6. Complete the acceptance steps below. Re-enable automatic backups and verify a successful post-upgrade backup before closing the change.

## DBA readiness checklist

Before setting readiness to `true`, record the evidence in your change ticket:

- DB system is on OL8 and GI 26ai, with no pending OS/GI maintenance. This workflow records the GI API value but does not independently inspect host OS/GI certification.
- Database is a 19c CDB and has no managed or manually configured Data Guard.
- ARCHIVELOG, flashback, recovery-area capacity and storage headroom are suitable.
- Database components, application/driver certification, licensing and the selected target release have been reviewed.
- An isolated test upgrade and restore rehearsal have passed; the recovery owner and backup retention are documented.
- The approved outage covers precheck, upgrade, acceptance and recovery contingency. No overlapping Console/API maintenance is allowed.

## Completion and recovery

The automation verifies a new upgrade-history entry for the requested action/version reaches `SUCCEEDED`, then checks database availability and the exact DB-home version. An old successful precheck or an `AVAILABLE` database by itself is not accepted as completion. History monitoring follows the [OCI upgrade history schema](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/database/models/oci.database.models.DatabaseUpgradeHistoryEntrySummary.html).

Afterward, run `sql/acceptance.sql` as an authorized DBA in the CDB root, compare results against your pre-upgrade baseline, inspect every application PDB, and test application login, reads, writes, batch jobs and integrations. The SQL report is read-only and intentionally not executed by the runner. A green workflow indicates control-plane success, not application acceptance.

Automatic backups remain disabled until the operator restores their configuration. Assign an operator to do this on success **or failure**, once OCI permits it. Review `COMPATIBLE` and old-home cleanup separately after acceptance. See [Oracle post-upgrade and rollback guidance](https://docs.oracle.com/en/cloud/paas/base-database/upgrade-db/).

Cancellation, CLI failure or timeout may leave OCI working. Do not rerun blindly. Inspect the database's OCI upgrade history, retain the operation ID from the log, and involve your DBA/Oracle Support. The code submits each action once and performs no automatic rollback. Follow the approved recovery plan; eligibility for service rollback depends on edition and operation state. A backup being ACTIVE is not proof that a restore rehearsal succeeded.

## Local verification

Run `python3 -m unittest discover -s tests -v`. The tests use simulated OCI responses and require no credentials. They exercise history correlation, failure handling and backup validation; they do not certify your tenancy, Oracle compatibility or application behavior.

The runner must already have OCI CLI installed. No runtime package download or database password is used by this workflow. The CLI request shape follows [OCI database upgrade](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/db/database/upgrade.html).
