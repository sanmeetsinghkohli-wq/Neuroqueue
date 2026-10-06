-- OPTIONAL. Only needed if you do NOT put SUPABASE_SERVICE_ROLE_KEY in backend/.env.
-- Creates the dedicated account the backend signs in as. Replace the two placeholders,
-- run once in the SQL editor, then set SUPABASE_SERVICE_EMAIL / SUPABASE_SERVICE_PASSWORD
-- in backend/.env to the same values. Never commit the filled-in file.

do $$
declare
  v_email text := 'REPLACE_WITH_SERVICE_EMAIL';        -- e.g. service@neuroqueue.internal
  v_password text := 'REPLACE_WITH_A_LONG_RANDOM_PASSWORD';
  v_id uuid := gen_random_uuid();
begin
  if exists (select 1 from auth.users where email = v_email) then
    raise notice 'service account already exists';
    return;
  end if;
  insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_app_meta_data, raw_user_meta_data,
                          created_at, updated_at, confirmation_token, recovery_token, email_change, email_change_token_new)
  values ('00000000-0000-0000-0000-000000000000', v_id, 'authenticated', 'authenticated', v_email,
          extensions.crypt(v_password, extensions.gen_salt('bf')), now(),
          '{"provider":"email","providers":["email"],"nq_role":"service"}'::jsonb, '{}'::jsonb, now(), now(), '', '', '', '');
  insert into auth.identities (id, user_id, provider_id, identity_data, provider, last_sign_in_at, created_at, updated_at)
  values (gen_random_uuid(), v_id, v_id::text, jsonb_build_object('sub', v_id::text, 'email', v_email), 'email', now(), now(), now());
end $$;
