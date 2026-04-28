---
cdate: 2026-04-21 14:20
mtime: 2026-04-21 14:26
---
create table public.admin_audit_logs (
  id uuid not null default gen_random_uuid (),
  admin_id uuid not null,
  action character varying(50) not null,
  target_table character varying(100) null,
  target_id uuid null,
  details jsonb null,
  ip_address character varying(45) null,
  user_agent text null,
  created_at timestamp with time zone null default now(),
  constraint admin_audit_logs_pkey primary key (id),
  constraint admin_audit_logs_admin_id_fkey foreign KEY (admin_id) references users (id)
) TABLESPACE pg_default;

create index IF not exists idx_audit_logs_action on public.admin_audit_logs using btree (action) TABLESPACE pg_default;

create index IF not exists idx_audit_logs_admin on public.admin_audit_logs using btree (admin_id) TABLESPACE pg_default;

create index IF not exists idx_audit_logs_created on public.admin_audit_logs using btree (created_at desc) TABLESPACE pg_default;

create index IF not exists idx_audit_logs_target on public.admin_audit_logs using btree (target_table, target_id) TABLESPACE pg_default;





create table public.api_usage_logs (
  id uuid not null default gen_random_uuid (),
  created_at timestamp with time zone null default now(),
  service_name text not null,
  api_name text not null,
  user_id uuid null,
  assessment_id uuid null,
  request_id text null,
  status text not null default 'success'::text,
  response_time_ms integer null,
  error_message text null,
  tokens_input integer null,
  tokens_output integer null,
  bytes_processed bigint null,
  duration_ms bigint null,
  estimated_cost numeric(10, 6) null default 0,
  constraint api_usage_logs_pkey primary key (id),
  constraint api_usage_logs_user_id_fkey foreign KEY (user_id) references auth.users (id) on delete set null
) TABLESPACE pg_default;

create index IF not exists idx_api_usage_created on public.api_usage_logs using btree (created_at) TABLESPACE pg_default;

create index IF not exists idx_api_usage_service on public.api_usage_logs using btree (service_name, created_at) TABLESPACE pg_default;

create index IF not exists idx_api_usage_status on public.api_usage_logs using btree (status) TABLESPACE pg_default;

create index IF not exists idx_api_usage_user on public.api_usage_logs using btree (user_id, created_at) TABLESPACE pg_default;




create table public.assessments (
  id uuid not null default gen_random_uuid (),
  candidate_id uuid not null,
  job_cert_id uuid not null,
  status character varying(20) null default 'started'::character varying,
  role_rating integer null,
  subskill_ratings jsonb null default '{}'::jsonb,
  interview_report text null,
  salary_expectations jsonb null default '{}'::jsonb,
  started_at timestamp with time zone null default now(),
  completed_at timestamp with time zone null,
  exam_video_url character varying(500) null,
  trust_score integer null,
  cheat_flag boolean null,
  failure_reason text null,
  question_evaluations jsonb null default '[]'::jsonb,
  scored_at timestamp with time zone null,
  interview_state character varying(30) null default null::character varying,
  interview_plan jsonb null,
  state_history jsonb null default '[]'::jsonb,
  interview_started_at timestamp with time zone null,
  interview_ended_at timestamp with time zone null,
  questions_asked integer null default 0,
  follow_ups_asked integer null default 0,
  skills_assessed jsonb null default '[]'::jsonb,
  pruned_skills jsonb null default '[]'::jsonb,
  written_skill_scores jsonb null default '{}'::jsonb,
  skill_comprehensive_scores jsonb null default '{}'::jsonb,
  job_comprehensive_score numeric(4, 2) null,
  final_report_structured jsonb null,
  updated_at timestamp with time zone null default now(),
  first_frame_image_url character varying(500) null,
  termination_reason character varying(255) null,
  dimension_scores jsonb null,
  dimension_details jsonb null,
  selected_scenarios jsonb null,
  estimated_candidate_level character varying(10) null,
  constraint assessments_pkey primary key (id),
  constraint assessments_candidate_id_fkey foreign KEY (candidate_id) references candidates (id) on delete CASCADE,
  constraint assessments_job_cert_id_fkey foreign KEY (job_cert_id) references job_certifications (id),
  constraint assessments_estimated_candidate_level_check check (
    (
      (estimated_candidate_level is null)
      or (
        (estimated_candidate_level)::text = any (
          (
            array[
              'junior'::character varying,
              'mid'::character varying,
              'senior'::character varying
            ]
          )::text[]
        )
      )
    )
  ),
  constraint assessments_interview_state_check check (
    (
      (interview_state is null)
      or (
        (interview_state)::text = any (
          array[
            ('INIT'::character varying)::text,
            ('SELF_INTRO'::character varying)::text,
            ('PROJECT_DEEP_DIVE'::character varying)::text,
            ('SKILL_ASSESSMENT'::character varying)::text,
            ('WRAP_UP'::character varying)::text,
            ('DONE'::character varying)::text,
            ('INTERRUPTED'::character varying)::text
          ]
        )
      )
    )
  ),
  constraint assessments_status_check check (
    (
      (status)::text = any (
        array[
          ('started'::character varying)::text,
          ('exam_done'::character varying)::text,
          ('interviewing'::character varying)::text,
          ('interview_done'::character varying)::text,
          ('processing'::character varying)::text,
          ('processed'::character varying)::text,
          ('scored'::character varying)::text,
          ('failed_cheating'::character varying)::text,
          ('abandoned'::character varying)::text
        ]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_assessments_candidate_id on public.assessments using btree (candidate_id) TABLESPACE pg_default;

create index IF not exists idx_assessments_candidate_status on public.assessments using btree (candidate_id, status) TABLESPACE pg_default;

create index IF not exists idx_assessments_interview_state on public.assessments using btree (interview_state) TABLESPACE pg_default
where
  (interview_state is not null);

create index IF not exists idx_assessments_job_cert_id on public.assessments using btree (job_cert_id) TABLESPACE pg_default;

create index IF not exists idx_assessments_started_at on public.assessments using btree (started_at desc) TABLESPACE pg_default;

create index IF not exists idx_assessments_status on public.assessments using btree (status) TABLESPACE pg_default;

create trigger after_assessment_complete
after
update on assessments for EACH row when (
  new.status::text = 'scored'::text
  and old.status::text <> 'scored'::text
)
execute FUNCTION trigger_update_assessment_embedding ();




create table public.candidate_current_skills (
  candidate_id uuid not null,
  sub_skill_id uuid not null,
  level integer not null,
  current_level integer null,
  updated_at timestamp with time zone null default now(),
  constraint candidate_current_skills_pkey primary key (candidate_id, sub_skill_id),
  constraint candidate_current_skills_candidate_id_fkey foreign KEY (candidate_id) references candidates (id) on delete CASCADE,
  constraint candidate_current_skills_sub_skill_id_fkey foreign KEY (sub_skill_id) references sub_skills (id),
  constraint candidate_current_skills_level_check check (
    (
      (level >= 1)
      and (level <= 10)
    )
  )
) TABLESPACE pg_default;


create table public.candidate_dimension_scores (
  candidate_id uuid not null,
  dim_id uuid not null,
  score double precision not null default 0.0,
  assessment_id uuid null,
  updated_at timestamp with time zone null default now(),
  constraint candidate_dimension_scores_pkey primary key (candidate_id, dim_id),
  constraint candidate_dimension_scores_assessment_id_fkey foreign KEY (assessment_id) references assessments (id),
  constraint candidate_dimension_scores_candidate_id_fkey foreign KEY (candidate_id) references candidates (id) on delete CASCADE,
  constraint candidate_dimension_scores_dim_id_fkey foreign KEY (dim_id) references dimensions (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists idx_cand_dim_scores_candidate on public.candidate_dimension_scores using btree (candidate_id) TABLESPACE pg_default;

create index IF not exists idx_cand_dim_scores_assessment on public.candidate_dimension_scores using btree (assessment_id) TABLESPACE pg_default;


create table public.candidate_payment_orders (
  id uuid not null default gen_random_uuid (),
  candidate_id uuid not null,
  out_trade_no character varying(100) not null,
  amount numeric(10, 2) not null,
  credits integer not null,
  status character varying(20) null default 'pending'::character varying,
  alipay_trade_no text null,
  alipay_callback jsonb null,
  created_at timestamp with time zone null default now(),
  completed_at timestamp with time zone null,
  constraint candidate_payment_orders_pkey primary key (id),
  constraint candidate_payment_orders_out_trade_no_key unique (out_trade_no),
  constraint candidate_payment_orders_candidate_id_fkey foreign KEY (candidate_id) references candidates (id) on delete CASCADE,
  constraint candidate_payment_orders_status_check check (
    (
      (status)::text = any (
        (
          array[
            'pending'::character varying,
            'success'::character varying,
            'failed'::character varying
          ]
        )::text[]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_candidate_payment_orders_candidate_id on public.candidate_payment_orders using btree (candidate_id) TABLESPACE pg_default;

create index IF not exists idx_candidate_payment_orders_status on public.candidate_payment_orders using btree (status) TABLESPACE pg_default;

create index IF not exists idx_candidate_payment_orders_out_trade_no on public.candidate_payment_orders using btree (out_trade_no) TABLESPACE pg_default;

create index IF not exists idx_candidate_payment_orders_created_at on public.candidate_payment_orders using btree (created_at desc) TABLESPACE pg_default;



create table public.candidate_report_unlocks (
  id uuid not null default gen_random_uuid (),
  candidate_id uuid not null,
  assessment_id uuid not null,
  credits_spent integer not null default 0,
  is_free boolean null default false,
  unlocked_at timestamp with time zone null default now(),
  constraint candidate_report_unlocks_pkey primary key (id),
  constraint candidate_report_unlocks_candidate_id_assessment_id_key unique (candidate_id, assessment_id),
  constraint candidate_report_unlocks_assessment_id_fkey foreign KEY (assessment_id) references assessments (id) on delete CASCADE,
  constraint candidate_report_unlocks_candidate_id_fkey foreign KEY (candidate_id) references candidates (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists idx_candidate_report_unlocks_candidate on public.candidate_report_unlocks using btree (candidate_id) TABLESPACE pg_default;

create index IF not exists idx_candidate_report_unlocks_assessment on public.candidate_report_unlocks using btree (assessment_id) TABLESPACE pg_default;




create table public.candidate_selected_skills (
  candidate_id uuid not null,
  sub_skill_id uuid not null,
  created_at timestamp with time zone null default now(),
  constraint candidate_selected_skills_pkey primary key (candidate_id, sub_skill_id),
  constraint candidate_selected_skills_candidate_id_fkey foreign KEY (candidate_id) references candidates (id) on delete CASCADE,
  constraint candidate_selected_skills_sub_skill_id_fkey foreign KEY (sub_skill_id) references sub_skills (id) on delete CASCADE
) TABLESPACE pg_default;


create table public.candidate_subskill_history (
  id uuid not null default gen_random_uuid (),
  candidate_id uuid not null,
  sub_skill_id uuid not null,
  assessment_id uuid not null,
  score double precision not null,
  relevance double precision null default 1.0,
  assessed_at timestamp with time zone null default now(),
  constraint candidate_subskill_history_pkey primary key (id),
  constraint candidate_subskill_history_assessment_id_fkey foreign KEY (assessment_id) references assessments (id),
  constraint candidate_subskill_history_candidate_id_fkey foreign KEY (candidate_id) references candidates (id) on delete CASCADE,
  constraint candidate_subskill_history_sub_skill_id_fkey foreign KEY (sub_skill_id) references sub_skills (id)
) TABLESPACE pg_default;

create index IF not exists idx_candidate_subskill_history_assessment_id on public.candidate_subskill_history using btree (assessment_id) TABLESPACE pg_default;

create index IF not exists idx_candidate_subskill_history_candidate_id on public.candidate_subskill_history using btree (candidate_id) TABLESPACE pg_default;


create table public.candidates (
  id uuid not null default gen_random_uuid (),
  user_id uuid not null,
  real_name character varying(100) null,
  id_card_hash character varying(255) null,
  id_verification_status character varying(20) null default 'pending'::character varying,
  preferred_city character varying(100) null,
  is_remote_ok boolean null default false,
  employment_preference character varying(20) null,
  salary_expectations jsonb null default '{}'::jsonb,
  updated_at timestamp with time zone null default now(),
  is_visible boolean null default true,
  concurrency_count integer null default 0,
  face_photo_path text null,
  id_card_encrypted text null,
  skill_vector extensions.vector null,
  assessment_embedding extensions.vector null,
  resume_embedding extensions.vector null,
  work_mode text null default 'both'::text,
  gender text null,
  age integer null,
  education_level text null,
  salary_min integer null,
  salary_max integer null,
  available_date text null,
  years_of_experience text null,
  industry_preferences jsonb null default '[]'::jsonb,
  company_size_preference text null,
  job_type_preferences jsonb null default '[]'::jsonb,
  benefits_priority jsonb null default '[]'::jsonb,
  credit_balance integer null default 0,
  free_report_used boolean null default false,
  source_enterprise_id uuid null,
  is_private_pool boolean null default false,
  constraint candidates_pkey primary key (id),
  constraint candidates_user_id_key unique (user_id),
  constraint candidates_user_id_fkey foreign KEY (user_id) references users (id) on delete CASCADE,
  constraint candidates_source_enterprise_id_fkey foreign KEY (source_enterprise_id) references employers (id) on delete set null,
  constraint candidates_work_mode_check check (
    (
      work_mode = any (
        array['onsite'::text, 'remote'::text, 'both'::text]
      )
    )
  ),
  constraint candidates_available_date_check check (
    (
      available_date = any (
        array[
          'immediate'::text,
          'within_week'::text,
          'within_month'::text,
          'flexible'::text
        ]
      )
    )
  ),
  constraint check_concurrency_count check (
    (
      (concurrency_count >= 0)
      and (concurrency_count <= 3)
    )
  ),
  constraint candidates_employment_preference_check check (
    (
      (employment_preference)::text = any (
        array[
          ('full_time'::character varying)::text,
          ('internship'::character varying)::text,
          ('both'::character varying)::text
        ]
      )
    )
  ),
  constraint candidates_gender_check check (
    (
      gender = any (
        array['male'::text, 'female'::text, 'other'::text]
      )
    )
  ),
  constraint candidates_id_verification_status_check check (
    (
      (id_verification_status)::text = any (
        array[
          ('pending'::character varying)::text,
          ('verified'::character varying)::text,
          ('failed'::character varying)::text
        ]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_candidates_assessment_embedding_hnsw on public.candidates using hnsw (assessment_embedding extensions.vector_cosine_ops)
with
  (m = '16', ef_construction = '64') TABLESPACE pg_default;

create index IF not exists idx_candidates_city on public.candidates using btree (preferred_city) TABLESPACE pg_default;

create index IF not exists idx_candidates_concurrency on public.candidates using btree (concurrency_count) TABLESPACE pg_default
where
  (concurrency_count < 3);

create index IF not exists idx_candidates_employment on public.candidates using btree (employment_preference) TABLESPACE pg_default;

create index IF not exists idx_candidates_is_visible on public.candidates using btree (is_visible) TABLESPACE pg_default
where
  (is_visible = true);

create index IF not exists idx_candidates_preferred_city on public.candidates using btree (preferred_city) TABLESPACE pg_default;

create index IF not exists idx_candidates_remote on public.candidates using btree (is_remote_ok) TABLESPACE pg_default
where
  (is_remote_ok = true);

create index IF not exists idx_candidates_resume_embedding_hnsw on public.candidates using hnsw (resume_embedding extensions.vector_cosine_ops)
with
  (m = '16', ef_construction = '64') TABLESPACE pg_default;

create index IF not exists idx_candidates_skill_vector_hnsw on public.candidates using hnsw (skill_vector extensions.vector_cosine_ops)
with
  (m = '16', ef_construction = '64') TABLESPACE pg_default;

create index IF not exists idx_candidates_user_id on public.candidates using btree (user_id) TABLESPACE pg_default;

create index IF not exists idx_candidates_private_pool on public.candidates using btree (is_private_pool) TABLESPACE pg_default
where
  (is_private_pool = true);

create index IF not exists idx_candidates_source_enterprise on public.candidates using btree (source_enterprise_id) TABLESPACE pg_default
where
  (source_enterprise_id is not null);




create table public.card_keys (
  id uuid not null default gen_random_uuid (),
  code character varying(30) not null,
  credits integer not null,
  price numeric(10, 2) not null default 0,
  batch_no character varying(50) null,
  status character varying(20) null default 'available'::character varying,
  expires_at timestamp with time zone null,
  redeemed_by uuid null,
  redeemed_at timestamp with time zone null,
  created_at timestamp with time zone null default now(),
  notes text null,
  constraint card_keys_pkey primary key (id),
  constraint card_keys_code_key unique (code),
  constraint card_keys_redeemed_by_fkey foreign KEY (redeemed_by) references candidates (id),
  constraint card_keys_status_check check (
    (
      (status)::text = any (
        (
          array[
            'available'::character varying,
            'redeemed'::character varying,
            'expired'::character varying,
            'disabled'::character varying
          ]
        )::text[]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_card_keys_code on public.card_keys using btree (code) TABLESPACE pg_default;

create index IF not exists idx_card_keys_status on public.card_keys using btree (status) TABLESPACE pg_default;

create index IF not exists idx_card_keys_batch on public.card_keys using btree (batch_no) TABLESPACE pg_default;

create index IF not exists idx_card_keys_redeemed_by on public.card_keys using btree (redeemed_by) TABLESPACE pg_default;


create table public.chat_attachment_uploads (
  id uuid not null default gen_random_uuid (),
  message_id uuid null,
  employer_id uuid not null,
  candidate_id uuid not null,
  uploader_user_id uuid not null,
  oss_key text not null,
  original_name character varying(255) not null,
  file_size integer not null,
  mime_type character varying(100) not null,
  upload_status character varying(20) null default 'pending'::character varying,
  created_at timestamp with time zone null default now(),
  completed_at timestamp with time zone null,
  constraint chat_attachment_uploads_pkey primary key (id),
  constraint chat_attachment_uploads_candidate_id_fkey foreign KEY (candidate_id) references candidates (id),
  constraint chat_attachment_uploads_employer_id_fkey foreign KEY (employer_id) references employers (id),
  constraint chat_attachment_uploads_message_id_fkey foreign KEY (message_id) references chat_messages (id) on delete CASCADE,
  constraint chat_attachment_uploads_uploader_user_id_fkey foreign KEY (uploader_user_id) references users (id),
  constraint chat_attachment_uploads_upload_status_check check (
    (
      (upload_status)::text = any (
        array[
          ('pending'::character varying)::text,
          ('completed'::character varying)::text,
          ('failed'::character varying)::text
        ]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_chat_attachment_uploads_message on public.chat_attachment_uploads using btree (message_id) TABLESPACE pg_default;

create index IF not exists idx_chat_attachment_uploads_status on public.chat_attachment_uploads using btree (upload_status) TABLESPACE pg_default
where
  ((upload_status):: text = 'pending'::text);

create table public.chat_messages (
  id uuid not null default gen_random_uuid (),
  employer_id uuid not null,
  candidate_id uuid not null,
  sender_user_id uuid not null,
  content text not null,
  is_read boolean null default false,
  created_at timestamp with time zone null default now(),
  is_pre_offer boolean null default false,
  message_type character varying(20) null default 'text'::character varying,
  attachment_url text null,
  attachment_name character varying(255) null,
  attachment_size integer null,
  attachment_mime_type character varying(100) null,
  thumbnail_url text null,
  is_recalled boolean null default false,
  recalled_at timestamp with time zone null,
  constraint chat_messages_pkey primary key (id),
  constraint chat_messages_candidate_id_fkey foreign KEY (candidate_id) references candidates (id) on delete CASCADE,
  constraint chat_messages_employer_id_fkey foreign KEY (employer_id) references employers (id) on delete CASCADE,
  constraint chat_messages_sender_user_id_fkey foreign KEY (sender_user_id) references users (id),
  constraint chat_messages_message_type_check check (
    (
      (message_type)::text = any (
        array[
          ('text'::character varying)::text,
          ('image'::character varying)::text,
          ('file'::character varying)::text,
          ('mixed'::character varying)::text
        ]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_chat_messages_candidate_id on public.chat_messages using btree (candidate_id) TABLESPACE pg_default;

create index IF not exists idx_chat_messages_conversation on public.chat_messages using btree (employer_id, candidate_id, created_at desc) TABLESPACE pg_default;

create index IF not exists idx_chat_messages_created_at on public.chat_messages using btree (created_at desc) TABLESPACE pg_default;

create index IF not exists idx_chat_messages_employer_id on public.chat_messages using btree (employer_id) TABLESPACE pg_default;

create index IF not exists idx_chat_messages_recalled on public.chat_messages using btree (is_recalled) TABLESPACE pg_default
where
  (is_recalled = true);

create index IF not exists idx_chat_messages_type on public.chat_messages using btree (message_type) TABLESPACE pg_default
where
  ((message_type):: text <> 'text'::text);


create table public.deduction_rules (
  id uuid not null default gen_random_uuid (),
  target_level integer not null,
  credit_cost integer not null default 0,
  updated_at timestamp with time zone null default now(),
  updated_by uuid null,
  constraint deduction_rules_pkey primary key (id),
  constraint deduction_rules_target_level_key unique (target_level),
  constraint deduction_rules_updated_by_fkey foreign KEY (updated_by) references users (id),
  constraint deduction_rules_credit_cost_check check ((credit_cost >= 0)),
  constraint deduction_rules_target_level_check check (
    (
      (target_level >= 1)
      and (target_level <= 10)
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_deduction_rules_level on public.deduction_rules using btree (target_level) TABLESPACE pg_default;



create table public.dimension_skill_rel (
  id uuid not null default gen_random_uuid (),
  dim_id uuid not null,
  sub_skill_id uuid not null,
  weight_in_dim double precision not null default 1.0,
  constraint dimension_skill_rel_pkey primary key (id),
  constraint dimension_skill_rel_dim_id_sub_skill_id_key unique (dim_id, sub_skill_id),
  constraint dimension_skill_rel_dim_id_fkey foreign KEY (dim_id) references dimensions (id) on delete CASCADE,
  constraint dimension_skill_rel_sub_skill_id_fkey foreign KEY (sub_skill_id) references sub_skills (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists idx_dim_skill_rel_dim on public.dimension_skill_rel using btree (dim_id) TABLESPACE pg_default;

create index IF not exists idx_dim_skill_rel_skill on public.dimension_skill_rel using btree (sub_skill_id) TABLESPACE pg_default;


create table public.dimensions (
  id uuid not null default gen_random_uuid (),
  name character varying(200) not null,
  description text null,
  created_at timestamp with time zone null default now(),
  constraint dimensions_pkey primary key (id)
) TABLESPACE pg_default;

create unique INDEX IF not exists idx_dimensions_name on public.dimensions using btree (name) TABLESPACE pg_default;


create table public.embedding_queue (
  id uuid not null default gen_random_uuid (),
  candidate_id uuid not null,
  embedding_type character varying(20) not null,
  text_length integer null,
  status character varying(20) null default 'pending'::character varying,
  error_message text null,
  retry_count integer null default 0,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  completed_at timestamp with time zone null,
  constraint embedding_queue_pkey primary key (id),
  constraint embedding_queue_candidate_id_embedding_type_key unique (candidate_id, embedding_type),
  constraint embedding_queue_candidate_id_fkey foreign KEY (candidate_id) references candidates (id) on delete CASCADE,
  constraint embedding_queue_embedding_type_check check (
    (
      (embedding_type)::text = any (
        array[
          ('resume'::character varying)::text,
          ('assessment'::character varying)::text,
          ('skill_vector'::character varying)::text
        ]
      )
    )
  ),
  constraint embedding_queue_status_check check (
    (
      (status)::text = any (
        array[
          ('pending'::character varying)::text,
          ('processing'::character varying)::text,
          ('completed'::character varying)::text,
          ('failed'::character varying)::text
        ]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_embedding_queue_created on public.embedding_queue using btree (created_at) TABLESPACE pg_default;

create index IF not exists idx_embedding_queue_status on public.embedding_queue using btree (status) TABLESPACE pg_default;



create table public.employer_jobs (
  id uuid not null default gen_random_uuid (),
  employer_id uuid not null,
  title character varying(200) not null,
  description text null,
  salary_range character varying(50) null,
  location character varying(100) null,
  job_cert_id uuid null,
  min_role_rating integer null,
  status character varying(20) null default 'draft'::character varying,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  responsibilities text null,
  requirements text null,
  company_info text null,
  constraint employer_jobs_pkey primary key (id),
  constraint employer_jobs_employer_id_fkey foreign KEY (employer_id) references employers (id) on delete CASCADE,
  constraint employer_jobs_job_cert_id_fkey foreign KEY (job_cert_id) references job_certifications (id),
  constraint employer_jobs_status_check check (
    (
      (status)::text = any (
        array[
          ('draft'::character varying)::text,
          ('published'::character varying)::text,
          ('closed'::character varying)::text
        ]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_employer_jobs_employer_id on public.employer_jobs using btree (employer_id) TABLESPACE pg_default;

create index IF not exists idx_employer_jobs_job_cert_id on public.employer_jobs using btree (job_cert_id) TABLESPACE pg_default;


create table public.employer_unlock_history (
  id uuid not null default gen_random_uuid (),
  employer_id uuid not null,
  candidate_id uuid not null,
  job_cert_id uuid null,
  credits_deducted integer not null,
  unlocked_at timestamp with time zone null default now(),
  access_level character varying(20) null default 'preview'::character varying,
  invite_status character varying(20) null default null::character varying,
  escrow_amount integer null default 0,
  expires_at timestamp with time zone null,
  constraint employer_unlock_history_pkey primary key (id),
  constraint employer_unlock_history_employer_candidate_unique unique (employer_id, candidate_id),
  constraint employer_unlock_history_candidate_id_fkey foreign KEY (candidate_id) references candidates (id),
  constraint employer_unlock_history_employer_id_fkey foreign KEY (employer_id) references employers (id) on delete CASCADE,
  constraint employer_unlock_history_job_cert_id_fkey foreign KEY (job_cert_id) references job_certifications (id),
  constraint check_access_level check (
    (
      (access_level)::text = any (
        array[
          ('preview'::character varying)::text,
          ('full'::character varying)::text
        ]
      )
    )
  ),
  constraint check_invite_status check (
    (
      (invite_status is null)
      or (
        (invite_status)::text = any (
          array[
            ('pending'::character varying)::text,
            ('accepted'::character varying)::text,
            ('rejected'::character varying)::text,
            ('expired'::character varying)::text
          ]
        )
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_employer_unlock_expires_at on public.employer_unlock_history using btree (expires_at) TABLESPACE pg_default
where
  (expires_at is not null);

create index IF not exists idx_employer_unlock_history_candidate_id on public.employer_unlock_history using btree (candidate_id) TABLESPACE pg_default;

create index IF not exists idx_employer_unlock_history_employer_id on public.employer_unlock_history using btree (employer_id) TABLESPACE pg_default;

create index IF not exists idx_employer_unlock_invite_status on public.employer_unlock_history using btree (invite_status) TABLESPACE pg_default
where
  ((invite_status)::text = 'pending'::text);

create index IF not exists idx_unlock_history_chat_permission on public.employer_unlock_history using btree (
  employer_id,
  candidate_id,
  access_level,
  invite_status
) TABLESPACE pg_default
where
  (
    ((access_level)::text = 'full'::text)
    and ((invite_status)::text = 'accepted'::text)
  );

create table public.employers (
  id uuid not null default gen_random_uuid (),
  user_id uuid not null,
  company_name character varying(200) null,
  license_url character varying(500) null,
  verification_status character varying(20) null default 'pending'::character varying,
  credit_balance integer null default 0,
  rejection_reason text null,
  email character varying(255) null,
  contact_name character varying(100) null,
  contact_phone character varying(20) null,
  verified_at timestamp with time zone null,
  verified_by uuid null,
  created_at timestamp with time zone null default now(),
  frozen_credits integer null default 0,
  credits integer null default 0,
  logo_url character varying(500) null,
  constraint employers_pkey primary key (id),
  constraint employers_user_id_key unique (user_id),
  constraint employers_user_id_fkey foreign KEY (user_id) references users (id) on delete CASCADE,
  constraint employers_verified_by_fkey foreign KEY (verified_by) references users (id) on delete set null,
  constraint check_frozen_credits_non_negative check ((frozen_credits >= 0)),
  constraint employers_verification_status_check check (
    (
      (verification_status)::text = any (
        array[
          ('pending'::character varying)::text,
          ('verified'::character varying)::text,
          ('rejected'::character varying)::text
        ]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_employers_created_at on public.employers using btree (created_at) TABLESPACE pg_default;

create index IF not exists idx_employers_verification_status on public.employers using btree (verification_status) TABLESPACE pg_default;




create table public.enterprise_invitations (
  id uuid not null default gen_random_uuid (),
  enterprise_id uuid not null,
  name character varying(100) not null,
  phone character varying(20) not null,
  target_job_id uuid null,
  status character varying(30) null default 'pending'::character varying,
  parsed_resume_data jsonb null,
  candidate_id uuid null,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  constraint enterprise_invitations_pkey primary key (id),
  constraint enterprise_invitations_candidate_id_fkey foreign KEY (candidate_id) references candidates (id),
  constraint enterprise_invitations_enterprise_id_fkey foreign KEY (enterprise_id) references employers (id) on delete CASCADE,
  constraint enterprise_invitations_target_job_id_fkey foreign KEY (target_job_id) references job_certifications (id),
  constraint enterprise_invitations_status_check check (
    (
      (status)::text = any (
        (
          array[
            'pending'::character varying,
            'sms_sent'::character varying,
            'registered'::character varying,
            'assessment_completed'::character varying
          ]
        )::text[]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_enterprise_invitations_enterprise on public.enterprise_invitations using btree (enterprise_id) TABLESPACE pg_default;

create index IF not exists idx_enterprise_invitations_phone on public.enterprise_invitations using btree (phone) TABLESPACE pg_default;



create table public.interview_evaluations (
  id uuid not null default gen_random_uuid (),
  interaction_id uuid not null,
  assessment_id uuid not null,
  sub_skill_id uuid null,
  question_id uuid null,
  score numeric(3, 1) not null,
  mini_review jsonb not null default '{}'::jsonb,
  scored_at timestamp with time zone null default now(),
  scoring_model character varying(50) null,
  tokens_used integer null,
  constraint interview_evaluations_pkey primary key (id),
  constraint interview_evaluations_interaction_id_key unique (interaction_id),
  constraint interview_evaluations_interaction_id_fkey foreign KEY (interaction_id) references interview_interactions (id) on delete CASCADE,
  constraint interview_evaluations_assessment_id_fkey foreign KEY (assessment_id) references assessments (id) on delete CASCADE,
  constraint interview_evaluations_question_id_fkey foreign KEY (question_id) references question_bank (id),
  constraint interview_evaluations_sub_skill_id_fkey foreign KEY (sub_skill_id) references sub_skills (id),
  constraint interview_evaluations_score_check check (
    (
      (score >= (0)::numeric)
      and (score <= (10)::numeric)
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_interview_evaluations_assessment on public.interview_evaluations using btree (assessment_id) TABLESPACE pg_default;

create index IF not exists idx_interview_evaluations_skill on public.interview_evaluations using btree (sub_skill_id) TABLESPACE pg_default
where
  (sub_skill_id is not null);


create table public.interview_feedback (
  id uuid not null default extensions.uuid_generate_v4 (),
  assessment_id uuid not null,
  raw_feedback text null,
  ai_summary text null,
  sentiment character varying(20) null,
  suggestion_category character varying(50) null,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  constraint interview_feedback_pkey primary key (id),
  constraint interview_feedback_assessment_id_fkey foreign KEY (assessment_id) references assessments (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists idx_interview_feedback_assessment_id on public.interview_feedback using btree (assessment_id) TABLESPACE pg_default;


create table public.interview_interactions (
  id uuid not null default gen_random_uuid (),
  assessment_id uuid not null,
  round_number integer not null,
  ai_question_text text null,
  candidate_audio_text text null,
  video_segment_url character varying(500) null,
  question_type character varying(20) null default 'skill'::character varying,
  target_sub_skill_id uuid null,
  phase character varying(30) null,
  sub_skill_id uuid null,
  is_follow_up boolean null default false,
  raw_asr_text text null,
  corrected_text text null,
  probe_evaluation jsonb null,
  duration_seconds integer null,
  question_id uuid null,
  follow_up_question text null,
  follow_up_raw_asr_text text null,
  follow_up_corrected_text text null,
  follow_up_duration_seconds integer null,
  follow_up_audio_url character varying(500) null,
  follow_up_probe_evaluation jsonb null,
  follow_up_video_url character varying(500) null,
  dim_id uuid null,
  scenario_id uuid null,
  project_skill_bonus jsonb null,
  routing_state character varying(20) null,
  constraint interview_interactions_pkey primary key (id),
  constraint interview_interactions_dim_id_fkey foreign KEY (dim_id) references dimensions (id),
  constraint interview_interactions_question_id_fkey foreign KEY (question_id) references question_bank (id),
  constraint interview_interactions_assessment_id_fkey foreign KEY (assessment_id) references assessments (id) on delete CASCADE,
  constraint interview_interactions_sub_skill_id_fkey foreign KEY (sub_skill_id) references sub_skills (id),
  constraint interview_interactions_target_sub_skill_id_fkey foreign KEY (target_sub_skill_id) references sub_skills (id),
  constraint interview_interactions_scenario_id_fkey foreign KEY (scenario_id) references scenarios (id),
  constraint interview_interactions_question_type_check check (
    (
      (question_type)::text = any (
        array[
          ('project_experience'::character varying)::text,
          ('skill'::character varying)::text
        ]
      )
    )
  ),
  constraint interview_interactions_routing_state_check check (
    (
      (routing_state is null)
      or (
        (routing_state)::text = any (
          (
            array[
              'adequate'::character varying,
              'excellent'::character varying,
              'stuck'::character varying
            ]
          )::text[]
        )
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_interview_interactions_phase on public.interview_interactions using btree (assessment_id, phase) TABLESPACE pg_default;

create index IF not exists idx_interview_interactions_skill on public.interview_interactions using btree (sub_skill_id) TABLESPACE pg_default
where
  (sub_skill_id is not null);

create index IF not exists idx_interview_interactions_dim on public.interview_interactions using btree (dim_id) TABLESPACE pg_default
where
  (dim_id is not null);

create index IF not exists idx_interview_interactions_scenario on public.interview_interactions using btree (scenario_id) TABLESPACE pg_default
where
  (scenario_id is not null);


create table public.invitation_templates (
  id uuid not null default gen_random_uuid (),
  employer_id uuid null,
  name character varying(100) not null,
  message_body text not null,
  salary_range character varying(50) null,
  is_system boolean null default false,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  constraint invitation_templates_pkey primary key (id),
  constraint invitation_templates_employer_id_fkey foreign KEY (employer_id) references employers (id) on delete CASCADE
) TABLESPACE pg_default;



create table public.job_applications (
  id uuid not null default gen_random_uuid (),
  job_id uuid not null,
  candidate_id uuid not null,
  status character varying(20) null default 'pending'::character varying,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  constraint job_applications_pkey primary key (id),
  constraint job_applications_job_candidate_unique unique (job_id, candidate_id),
  constraint job_applications_candidate_id_fkey foreign KEY (candidate_id) references candidates (id) on delete CASCADE,
  constraint job_applications_job_id_fkey foreign KEY (job_id) references employer_jobs (id) on delete CASCADE,
  constraint job_applications_status_check check (
    (
      (status)::text = any (
        array[
          ('pending'::character varying)::text,
          ('reviewed'::character varying)::text,
          ('accepted'::character varying)::text,
          ('rejected'::character varying)::text
        ]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_job_applications_candidate_id on public.job_applications using btree (candidate_id) TABLESPACE pg_default;

create index IF not exists idx_job_applications_job_id on public.job_applications using btree (job_id) TABLESPACE pg_default;



create table public.job_categories (
  id uuid not null default gen_random_uuid (),
  name character varying(100) not null,
  sort_order integer not null default 0,
  created_at timestamp with time zone null default now(),
  constraint job_categories_pkey primary key (id)
) TABLESPACE pg_default;

create index IF not exists idx_job_categories_sort on public.job_categories using btree (sort_order) TABLESPACE pg_default;


create table public.job_certifications (
  id uuid not null default gen_random_uuid (),
  title character varying(200) not null,
  description text null,
  salary_range character varying(50) null,
  level_checklist jsonb null default '{}'::jsonb,
  unlock_cost_rule jsonb null default '{}'::jsonb,
  ai_interviewer_prompt text null,
  report_template text null,
  contract_type character varying(20) null,
  billing_mode character varying(20) null,
  created_at timestamp with time zone null default now(),
  description_embedding extensions.vector null,
  publish_status character varying(20) null default 'published'::character varying,
  creation_step integer null default 8,
  generation_config jsonb null,
  scenario_mode character varying(20) null default 'selective'::character varying,
  max_scenario_dimensions integer null default 2,
  is_hidden boolean not null default false,
  category_id uuid null,
  sort_order integer not null default 0,
  max_retry_attempts integer null,
  constraint job_certifications_pkey primary key (id),
  constraint job_certifications_category_id_fkey foreign KEY (category_id) references job_categories (id) on delete set null,
  constraint job_certifications_billing_mode_check check (
    (
      (billing_mode)::text = any (
        array[
          ('monthly'::character varying)::text,
          ('hourly'::character varying)::text
        ]
      )
    )
  ),
  constraint job_certifications_contract_type_check check (
    (
      (contract_type)::text = any (
        array[
          ('full_time'::character varying)::text,
          ('part_time'::character varying)::text
        ]
      )
    )
  ),
  constraint job_certifications_publish_status_check check (
    (
      (publish_status)::text = any (
        (
          array[
            'draft'::character varying,
            'generating'::character varying,
            'review'::character varying,
            'published'::character varying,
            'archived'::character varying
          ]
        )::text[]
      )
    )
  ),
  constraint job_certifications_scenario_mode_check check (
    (
      (scenario_mode)::text = any (
        (
          array[
            'all'::character varying,
            'selective'::character varying
          ]
        )::text[]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_job_certifications_embedding_hnsw on public.job_certifications using hnsw (
  description_embedding extensions.vector_cosine_ops
)
with
  (m = '16', ef_construction = '64') TABLESPACE pg_default;

create index IF not exists idx_job_certs_publish_status on public.job_certifications using btree (publish_status) TABLESPACE pg_default;

create index IF not exists idx_job_certifications_category on public.job_certifications using btree (category_id) TABLESPACE pg_default;

create index IF not exists idx_job_certifications_sort on public.job_certifications using btree (sort_order) TABLESPACE pg_default;


create table public.job_dimension_weights (
  id uuid not null default gen_random_uuid (),
  job_cert_id uuid not null,
  dim_id uuid not null,
  weight double precision not null default 1.0,
  requires_scenario boolean not null default true,
  constraint job_dimension_weights_pkey primary key (id),
  constraint job_dimension_weights_job_cert_id_dim_id_key unique (job_cert_id, dim_id),
  constraint job_dimension_weights_dim_id_fkey foreign KEY (dim_id) references dimensions (id) on delete CASCADE,
  constraint job_dimension_weights_job_cert_id_fkey foreign KEY (job_cert_id) references job_certifications (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists idx_job_dim_weights_job on public.job_dimension_weights using btree (job_cert_id) TABLESPACE pg_default;

create index IF not exists idx_job_dim_weights_dim on public.job_dimension_weights using btree (dim_id) TABLESPACE pg_default;


create table public.job_skill_weights (
  id uuid not null default gen_random_uuid (),
  job_cert_id uuid not null,
  sub_skill_id uuid not null,
  weight double precision not null default 1.0,
  is_required boolean null default false,
  assessment_method character varying(20) null default 'both'::character varying,
  constraint job_skill_weights_pkey primary key (id),
  constraint job_skill_weights_job_cert_id_sub_skill_id_key unique (job_cert_id, sub_skill_id),
  constraint job_skill_weights_job_cert_id_fkey foreign KEY (job_cert_id) references job_certifications (id) on delete CASCADE,
  constraint job_skill_weights_sub_skill_id_fkey foreign KEY (sub_skill_id) references sub_skills (id) on delete CASCADE,
  constraint job_skill_weights_assessment_method_check check (
    (
      (assessment_method)::text = any (
        (
          array[
            'written'::character varying,
            'interview'::character varying,
            'fill_blank'::character varying,
            'both'::character varying,
            'short_answer'::character varying
          ]
        )::text[]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_job_skill_weights_job_cert_id on public.job_skill_weights using btree (job_cert_id) TABLESPACE pg_default;

create index IF not exists idx_job_skill_weights_required on public.job_skill_weights using btree (job_cert_id, is_required) TABLESPACE pg_default
where
  (is_required = true);

create index IF not exists idx_job_skill_weights_sub_skill_id on public.job_skill_weights using btree (sub_skill_id) TABLESPACE pg_default;


create table public.notification_logs (
  id uuid not null default gen_random_uuid (),
  recipient_user_id uuid not null,
  notification_type character varying(50) not null,
  content text null,
  related_unlock_id uuid null,
  status character varying(20) null default 'pending'::character varying,
  error_message text null,
  sent_at timestamp with time zone null default now(),
  constraint notification_logs_pkey primary key (id),
  constraint notification_logs_recipient_user_id_fkey foreign KEY (recipient_user_id) references users (id),
  constraint notification_logs_related_unlock_id_fkey foreign KEY (related_unlock_id) references employer_unlock_history (id)
) TABLESPACE pg_default;

create index IF not exists idx_notification_logs_recipient on public.notification_logs using btree (recipient_user_id, sent_at desc) TABLESPACE pg_default;


create table public.page_events (
  id uuid not null default gen_random_uuid (),
  created_at timestamp with time zone null default now(),
  user_id uuid null,
  session_id text null,
  page_path text not null,
  page_name text null,
  referrer_path text null,
  event_type text not null,
  event_name text null,
  time_on_page_ms integer null,
  scroll_depth_percent integer null,
  device_type text null,
  browser text null,
  os text null,
  metadata jsonb null default '{}'::jsonb,
  constraint page_events_pkey primary key (id),
  constraint page_events_user_id_fkey foreign KEY (user_id) references auth.users (id) on delete set null
) TABLESPACE pg_default;

create index IF not exists idx_page_events_path on public.page_events using btree (page_path, created_at) TABLESPACE pg_default;

create index IF not exists idx_page_events_session on public.page_events using btree (session_id) TABLESPACE pg_default;

create index IF not exists idx_page_events_type on public.page_events using btree (event_type, created_at) TABLESPACE pg_default;

create index IF not exists idx_page_events_user on public.page_events using btree (user_id, created_at) TABLESPACE pg_default;


create table public.payment_orders (
  id uuid not null default gen_random_uuid (),
  employer_id uuid not null,
  out_trade_no character varying(100) not null,
  alipay_trade_no character varying(100) null,
  amount numeric(10, 2) not null,
  credits integer not null,
  status character varying(20) null default 'pending'::character varying,
  created_at timestamp with time zone null default now(),
  completed_at timestamp with time zone null,
  alipay_callback jsonb null,
  constraint payment_orders_pkey primary key (id),
  constraint payment_orders_out_trade_no_key unique (out_trade_no),
  constraint payment_orders_employer_id_fkey foreign KEY (employer_id) references employers (id) on delete CASCADE,
  constraint payment_orders_status_check check (
    (
      (status)::text = any (
        array[
          ('pending'::character varying)::text,
          ('success'::character varying)::text,
          ('failed'::character varying)::text
        ]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_payment_orders_created_at on public.payment_orders using btree (created_at desc) TABLESPACE pg_default;

create index IF not exists idx_payment_orders_employer_id on public.payment_orders using btree (employer_id) TABLESPACE pg_default;

create index IF not exists idx_payment_orders_status on public.payment_orders using btree (status) TABLESPACE pg_default;


create table public.personal_profiles (
  id uuid not null default gen_random_uuid (),
  candidate_id uuid not null,
  resume_url character varying(500) null,
  resume_text text null,
  education jsonb null default '[]'::jsonb,
  work_experience jsonb null default '[]'::jsonb,
  projects jsonb null default '[]'::jsonb,
  certifications jsonb null default '[]'::jsonb,
  awards jsonb null default '[]'::jsonb,
  constraint personal_profiles_pkey primary key (id),
  constraint personal_profiles_candidate_id_key unique (candidate_id),
  constraint personal_profiles_candidate_id_fkey foreign KEY (candidate_id) references candidates (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists idx_personal_profiles_resume_text_fts on public.personal_profiles using gin (
  to_tsvector(
    'simple'::regconfig,
    COALESCE(resume_text, ''::text)
  )
) TABLESPACE pg_default;

create index IF not exists idx_personal_profiles_resume_text_gin on public.personal_profiles using gin (
  to_tsvector(
    'simple'::regconfig,
    COALESCE(resume_text, ''::text)
  )
) TABLESPACE pg_default;

create trigger after_resume_upload
after INSERT
or
update on personal_profiles for EACH row when (new.resume_text is not null)
execute FUNCTION trigger_generate_resume_embedding ();


create table public.proctoring_reports (
  id uuid not null default gen_random_uuid (),
  assessment_id uuid not null,
  provider_session_id character varying(255) null,
  overall_trust_score integer null,
  tab_switch_count integer null default 0,
  browser_resize_count integer null default 0,
  face_detection_issues integer null default 0,
  audio_anomalies integer null default 0,
  incident_log jsonb null default '[]'::jsonb,
  report_json jsonb null,
  created_at timestamp with time zone null default now(),
  constraint proctoring_reports_pkey primary key (id),
  constraint proctoring_reports_assessment_id_key unique (assessment_id),
  constraint proctoring_reports_assessment_id_fkey foreign KEY (assessment_id) references assessments (id) on delete CASCADE
) TABLESPACE pg_default;


create table public.question_bank (
  id uuid not null default gen_random_uuid (),
  content text not null,
  reference_answer text null,
  type character varying(20) not null,
  options jsonb null default '[]'::jsonb,
  sub_skill_id uuid null,
  difficulty character varying(10) null,
  correct_option integer null,
  scoring_checklist jsonb null default '[]'::jsonb,
  evaluation_checklist jsonb null,
  blank_answers jsonb null,
  constraint question_bank_pkey primary key (id),
  constraint question_bank_sub_skill_id_fkey foreign KEY (sub_skill_id) references sub_skills (id),
  constraint question_bank_correct_option_check check (
    (
      (correct_option >= 0)
      and (correct_option <= 3)
    )
  ),
  constraint question_bank_difficulty_check check (
    (
      (difficulty)::text = any (
        array[
          ('easy'::character varying)::text,
          ('medium'::character varying)::text,
          ('hard'::character varying)::text
        ]
      )
    )
  ),
  constraint question_bank_type_check check (
    (
      (type)::text = any (
        (
          array[
            'written'::character varying,
            'interview'::character varying,
            'fill_blank'::character varying,
            'short_answer'::character varying
          ]
        )::text[]
      )
    )
  )
) TABLESPACE pg_default;

create unique INDEX IF not exists idx_question_bank_unique_content on public.question_bank using btree (md5(content), type, sub_skill_id) TABLESPACE pg_default;



create table public.report_unlock_records (
  id uuid not null default gen_random_uuid (),
  enterprise_id uuid not null,
  candidate_id uuid not null,
  assessment_id uuid not null,
  unlock_cost integer null default 200,
  created_at timestamp with time zone null default now(),
  constraint report_unlock_records_pkey primary key (id),
  constraint report_unlock_records_enterprise_id_candidate_id_assessment_key unique (enterprise_id, candidate_id, assessment_id),
  constraint report_unlock_records_assessment_id_fkey foreign KEY (assessment_id) references assessments (id),
  constraint report_unlock_records_candidate_id_fkey foreign KEY (candidate_id) references candidates (id),
  constraint report_unlock_records_enterprise_id_fkey foreign KEY (enterprise_id) references employers (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists idx_report_unlock_enterprise on public.report_unlock_records using btree (enterprise_id) TABLESPACE pg_default;


create table public.scenarios (
  id uuid not null default gen_random_uuid (),
  dim_id uuid not null,
  context_text text not null,
  constraints text null,
  difficulty character varying(10) null default 'medium'::character varying,
  category character varying(100) null,
  created_at timestamp with time zone null default now(),
  constraint scenarios_pkey primary key (id),
  constraint scenarios_dim_id_fkey foreign KEY (dim_id) references dimensions (id) on delete CASCADE,
  constraint scenarios_difficulty_check check (
    (
      (difficulty)::text = any (
        (
          array[
            'easy'::character varying,
            'medium'::character varying,
            'hard'::character varying
          ]
        )::text[]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_scenarios_dim on public.scenarios using btree (dim_id) TABLESPACE pg_default;

create index IF not exists idx_scenarios_category on public.scenarios using btree (category) TABLESPACE pg_default;

create table public.scoring_logs (
  id uuid not null default gen_random_uuid (),
  assessment_id uuid not null,
  started_at timestamp with time zone null default now(),
  completed_at timestamp with time zone null,
  status character varying(50) null,
  tokens_used integer null,
  error_message text null,
  details jsonb null,
  constraint scoring_logs_pkey primary key (id),
  constraint scoring_logs_assessment_id_fkey foreign KEY (assessment_id) references assessments (id) on delete CASCADE
) TABLESPACE pg_default;


create table public.sms_otp_codes (
  id uuid not null default gen_random_uuid (),
  phone text not null,
  code text not null,
  purpose text not null default 'register'::text,
  used boolean not null default false,
  expires_at timestamp with time zone not null,
  created_at timestamp with time zone not null default now(),
  constraint sms_otp_codes_pkey primary key (id)
) TABLESPACE pg_default;

create index IF not exists idx_sms_otp_codes_lookup on public.sms_otp_codes using btree (phone, purpose, used, expires_at) TABLESPACE pg_default;


create table public.sub_skills (
  id uuid not null default gen_random_uuid (),
  name character varying(100) not null,
  definition text null,
  embedding extensions.vector null,
  vector_index integer null,
  constraint sub_skills_pkey primary key (id),
  constraint sub_skills_vector_index_key unique (vector_index)
) TABLESPACE pg_default;

create index IF not exists idx_sub_skills_embedding_hnsw on public.sub_skills using hnsw (embedding extensions.vector_cosine_ops)
with
  (m = '16', ef_construction = '64') TABLESPACE pg_default;

create unique INDEX IF not exists idx_sub_skills_name on public.sub_skills using btree (name) TABLESPACE pg_default;


create table public.subskill_exam_results (
  id uuid not null default gen_random_uuid (),
  assessment_id uuid not null,
  sub_skill_id uuid not null,
  easy_correct boolean not null default false,
  hard_correct boolean not null default false,
  result_code character varying(10) not null default '❌❌'::character varying,
  created_at timestamp with time zone null default now(),
  constraint subskill_exam_results_pkey primary key (id),
  constraint subskill_exam_results_assessment_id_sub_skill_id_key unique (assessment_id, sub_skill_id),
  constraint subskill_exam_results_assessment_id_fkey foreign KEY (assessment_id) references assessments (id) on delete CASCADE,
  constraint subskill_exam_results_sub_skill_id_fkey foreign KEY (sub_skill_id) references sub_skills (id)
) TABLESPACE pg_default;

create index IF not exists idx_subskill_exam_results_assessment on public.subskill_exam_results using btree (assessment_id) TABLESPACE pg_default;

create index IF not exists idx_subskill_exam_results_skill on public.subskill_exam_results using btree (sub_skill_id) TABLESPACE pg_default;


create table public.system_quotas (
  id uuid not null default gen_random_uuid (),
  quota_key text not null,
  quota_type text not null,
  service_name text null,
  limit_value bigint not null,
  current_value bigint null default 0,
  warning_threshold numeric(3, 2) null default 0.80,
  reset_at timestamp with time zone null,
  last_reset_at timestamp with time zone null,
  is_enabled boolean null default true,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  constraint system_quotas_pkey primary key (id),
  constraint system_quotas_quota_key_key unique (quota_key)
) TABLESPACE pg_default;

create table public.system_settings (
  key character varying(100) not null,
  value jsonb not null default '{}'::jsonb,
  description text null,
  updated_at timestamp with time zone null default now(),
  updated_by uuid null,
  constraint system_settings_pkey primary key (key),
  constraint system_settings_updated_by_fkey foreign KEY (updated_by) references users (id)
) TABLESPACE pg_default;

create table public.usage_summary (
  id uuid not null default gen_random_uuid (),
  period_date date not null,
  service_name text not null,
  api_name text not null,
  total_calls integer null default 0,
  success_calls integer null default 0,
  failed_calls integer null default 0,
  total_tokens_input bigint null default 0,
  total_tokens_output bigint null default 0,
  total_bytes bigint null default 0,
  total_duration_ms bigint null default 0,
  estimated_cost numeric(12, 4) null default 0,
  avg_response_time_ms integer null,
  min_response_time_ms integer null,
  max_response_time_ms integer null,
  p50_response_time_ms integer null,
  p95_response_time_ms integer null,
  p99_response_time_ms integer null,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  constraint usage_summary_pkey primary key (id),
  constraint usage_summary_period_date_service_name_api_name_key unique (period_date, service_name, api_name)
) TABLESPACE pg_default;

create index IF not exists idx_usage_summary_date on public.usage_summary using btree (period_date) TABLESPACE pg_default;

create index IF not exists idx_usage_summary_service on public.usage_summary using btree (service_name) TABLESPACE pg_default;


create table public.user_activity_logs (
  id uuid not null default gen_random_uuid (),
  created_at timestamp with time zone null default now(),
  user_id uuid null,
  user_type text not null default 'candidate'::text,
  activity_type text not null,
  activity_detail text null,
  ip_address inet null,
  user_agent text null,
  device_type text null,
  success boolean null default true,
  error_message text null,
  metadata jsonb null default '{}'::jsonb,
  constraint user_activity_logs_pkey primary key (id),
  constraint user_activity_logs_user_id_fkey foreign KEY (user_id) references auth.users (id) on delete set null
) TABLESPACE pg_default;

create index IF not exists idx_user_activity_created on public.user_activity_logs using btree (created_at) TABLESPACE pg_default;

create index IF not exists idx_user_activity_type on public.user_activity_logs using btree (activity_type, created_at) TABLESPACE pg_default;

create index IF not exists idx_user_activity_user on public.user_activity_logs using btree (user_id, created_at) TABLESPACE pg_default;


create table public.users (
  id uuid not null default gen_random_uuid (),
  phone character varying(20) null,
  email character varying(255) null,
  role character varying(20) not null,
  created_at timestamp with time zone null default now(),
  last_login timestamp with time zone null,
  constraint users_pkey primary key (id),
  constraint users_email_key unique (email),
  constraint users_phone_key unique (phone),
  constraint users_role_check check (
    (
      (role)::text = any (
        array[
          ('candidate'::character varying)::text,
          ('employer'::character varying)::text,
          ('admin'::character varying)::text
        ]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists idx_users_email on public.users using btree (email) TABLESPACE pg_default;

create index IF not exists idx_users_phone on public.users using btree (phone) TABLESPACE pg_default;

create index IF not exists idx_users_role on public.users using btree (role) TABLESPACE pg_default;


create table public.vector_update_logs (
  id uuid not null default gen_random_uuid (),
  candidate_id uuid null,
  assessment_id uuid null,
  skills_updated integer null,
  vector_length integer null,
  previous_vector jsonb null,
  new_vector jsonb null,
  created_at timestamp with time zone null default now(),
  constraint vector_update_logs_pkey primary key (id),
  constraint vector_update_logs_assessment_id_fkey foreign KEY (assessment_id) references assessments (id),
  constraint vector_update_logs_candidate_id_fkey foreign KEY (candidate_id) references candidates (id)
) TABLESPACE pg_default;

create index IF not exists idx_vector_update_logs_candidate on public.vector_update_logs using btree (candidate_id) TABLESPACE pg_default;



create table public.written_attempts (
  id uuid not null default gen_random_uuid (),
  assessment_id uuid not null,
  question_id uuid not null,
  candidate_answer text null,
  score double precision null,
  is_correct boolean null,
  selected_option integer null,
  feedback text null,
  constraint written_attempts_pkey primary key (id),
  constraint written_attempts_assessment_id_fkey foreign KEY (assessment_id) references assessments (id) on delete CASCADE,
  constraint written_attempts_question_id_fkey foreign KEY (question_id) references question_bank (id)
) TABLESPACE pg_default;