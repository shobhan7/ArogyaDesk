-- MySQL reference schema for ArogyaDesk.
-- The application also creates these tables through SQLAlchemy on startup.
-- Money is stored as integer paise so a fee of Rs 500 is 50000.

CREATE TABLE user_account (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  email VARCHAR(160) NOT NULL UNIQUE,
  password_hash VARCHAR(200) NOT NULL,
  full_name VARCHAR(120) NOT NULL,
  phone VARCHAR(20) NULL,
  role VARCHAR(32) NOT NULL,
  enabled BOOLEAN NOT NULL,
  created_at DATETIME(6) NOT NULL
);

CREATE TABLE clinic (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(160) NOT NULL,
  city VARCHAR(80) NOT NULL,
  address VARCHAR(255) NOT NULL,
  phone VARCHAR(20) NULL,
  created_at DATETIME(6) NOT NULL
);

CREATE TABLE department (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  clinic_id BIGINT NOT NULL,
  name VARCHAR(120) NOT NULL,
  code VARCHAR(16) NOT NULL,
  UNIQUE KEY uq_department_code (clinic_id, code),
  CONSTRAINT fk_department_clinic FOREIGN KEY (clinic_id) REFERENCES clinic (id)
);

CREATE TABLE doctor (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL UNIQUE,
  department_id BIGINT NOT NULL,
  registration_number VARCHAR(40) NOT NULL UNIQUE,
  consultation_fee_paise INT NOT NULL,
  active BOOLEAN NOT NULL,
  CONSTRAINT fk_doctor_user FOREIGN KEY (user_id) REFERENCES user_account (id),
  CONSTRAINT fk_doctor_department FOREIGN KEY (department_id) REFERENCES department (id)
);

CREATE TABLE patient (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL UNIQUE,
  date_of_birth DATE NULL,
  gender VARCHAR(16) NULL,
  blood_group VARCHAR(8) NULL,
  CONSTRAINT fk_patient_user FOREIGN KEY (user_id) REFERENCES user_account (id)
);

CREATE TABLE weekly_schedule (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  doctor_id BIGINT NOT NULL,
  day_of_week INT NOT NULL,
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  slot_minutes INT NOT NULL,
  UNIQUE KEY uq_schedule_block (doctor_id, day_of_week, start_time),
  CONSTRAINT fk_schedule_doctor FOREIGN KEY (doctor_id) REFERENCES doctor (id)
);

CREATE TABLE appointment_slot (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  doctor_id BIGINT NOT NULL,
  slot_date DATE NOT NULL,
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  status VARCHAR(16) NOT NULL,
  version INT NOT NULL,
  UNIQUE KEY uq_slot_doctor_date_start (doctor_id, slot_date, start_time),
  KEY idx_slot_doctor_date_status (doctor_id, slot_date, status),
  CONSTRAINT fk_slot_doctor FOREIGN KEY (doctor_id) REFERENCES doctor (id)
);

CREATE TABLE appointment (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  slot_id BIGINT NOT NULL,
  patient_id BIGINT NOT NULL,
  doctor_id BIGINT NOT NULL,
  status VARCHAR(24) NOT NULL,
  token_number INT NOT NULL,
  booked_at DATETIME(6) NOT NULL,
  cancel_reason VARCHAR(255) NULL,
  day_guard VARCHAR(80) NULL UNIQUE,
  KEY idx_appointment_patient (patient_id, status),
  KEY idx_appointment_doctor (doctor_id, status),
  CONSTRAINT fk_appointment_slot FOREIGN KEY (slot_id) REFERENCES appointment_slot (id),
  CONSTRAINT fk_appointment_patient FOREIGN KEY (patient_id) REFERENCES patient (id),
  CONSTRAINT fk_appointment_doctor FOREIGN KEY (doctor_id) REFERENCES doctor (id)
);

CREATE TABLE queue_token (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  appointment_id BIGINT NOT NULL UNIQUE,
  doctor_id BIGINT NOT NULL,
  queue_date DATE NOT NULL,
  token_number INT NOT NULL,
  status VARCHAR(16) NOT NULL,
  UNIQUE KEY uq_token_number (doctor_id, queue_date, token_number),
  CONSTRAINT fk_token_appointment FOREIGN KEY (appointment_id) REFERENCES appointment (id),
  CONSTRAINT fk_token_doctor FOREIGN KEY (doctor_id) REFERENCES doctor (id)
);

CREATE TABLE encounter (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  appointment_id BIGINT NOT NULL UNIQUE,
  doctor_id BIGINT NOT NULL,
  patient_id BIGINT NOT NULL,
  clinical_notes TEXT NOT NULL,
  created_at DATETIME(6) NOT NULL,
  CONSTRAINT fk_encounter_appointment FOREIGN KEY (appointment_id) REFERENCES appointment (id)
);

CREATE TABLE prescription_item (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  encounter_id BIGINT NOT NULL,
  medicine_name VARCHAR(160) NOT NULL,
  dosage VARCHAR(80) NOT NULL,
  duration_days INT NOT NULL,
  instructions VARCHAR(255) NULL,
  CONSTRAINT fk_item_encounter FOREIGN KEY (encounter_id) REFERENCES encounter (id)
);

CREATE TABLE invoice (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  appointment_id BIGINT NOT NULL UNIQUE,
  patient_id BIGINT NOT NULL,
  amount_paise INT NOT NULL,
  status VARCHAR(16) NOT NULL,
  issued_at DATETIME(6) NOT NULL,
  CONSTRAINT fk_invoice_appointment FOREIGN KEY (appointment_id) REFERENCES appointment (id),
  CONSTRAINT fk_invoice_patient FOREIGN KEY (patient_id) REFERENCES patient (id)
);

CREATE TABLE payment (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  invoice_id BIGINT NOT NULL,
  amount_paise INT NOT NULL,
  method VARCHAR(24) NOT NULL,
  reference_code VARCHAR(64) NULL,
  paid_at DATETIME(6) NOT NULL,
  CONSTRAINT fk_payment_invoice FOREIGN KEY (invoice_id) REFERENCES invoice (id)
);

CREATE TABLE outbox_event (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  aggregate_type VARCHAR(40) NOT NULL,
  aggregate_id BIGINT NOT NULL,
  event_type VARCHAR(60) NOT NULL,
  payload TEXT NOT NULL,
  created_at DATETIME(6) NOT NULL,
  published_at DATETIME(6) NULL,
  KEY idx_outbox_unpublished (published_at, id)
);

CREATE TABLE notification_log (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  event_id BIGINT NOT NULL UNIQUE,
  event_type VARCHAR(60) NOT NULL,
  payload TEXT NOT NULL,
  received_at DATETIME(6) NOT NULL
);

CREATE TABLE audit_entry (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  actor_id BIGINT NULL,
  action VARCHAR(60) NOT NULL,
  entity_type VARCHAR(40) NOT NULL,
  entity_id BIGINT NULL,
  detail VARCHAR(500) NULL,
  created_at DATETIME(6) NOT NULL
);
