-- Run as an authorized DBA in CDB$ROOT before and after maintenance.
-- Review results per PDB; this report does not automatically certify acceptance.
whenever sqlerror exit failure
set pagesize 200 linesize 220 trimspool on
select banner_full from v$version;
select name, cdb, open_mode, database_role, log_mode, flashback_on from v$database;
select inst_id, instance_name, status, version_full from gv$instance order by inst_id;
select con_id, name, open_mode, restricted from v$pdbs order by con_id;
select con_id, comp_id, version, status from cdb_registry order by con_id, comp_id;
select con_id, owner, object_type, count(*) invalid_count
from cdb_objects where status = 'INVALID'
group by con_id, owner, object_type order by con_id, owner, object_type;
select con_id, patch_id, action, status, action_time
from cdb_registry_sqlpatch order by action_time;
select name, value from v$parameter where name = 'compatible';
exit success
