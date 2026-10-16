
CREATE TABLE IF NOT EXISTS public."DeletedParticipantsBackup" (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id text NOT NULL,
  participant_id text,
  display_name text,
  deleted_at timestamptz NOT NULL DEFAULT now(),
  deleted_by text,                 
  storage_path text NOT NULL       
);

CREATE INDEX IF NOT EXISTS deleted_participants_backup_user_id_idx
  ON public."DeletedParticipantsBackup" (user_id);
