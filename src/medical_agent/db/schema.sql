-- =====================================================================
-- 医疗预约系统数据库 Schema v2
-- 增量：乐观锁（version）、幂等性（idempotency_key）、审计日志
-- =====================================================================

-- 1. 科室表
CREATE TABLE IF NOT EXISTS departments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_departments_name ON departments(name);

-- 2. 医生表
CREATE TABLE IF NOT EXISTS doctors (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    department   TEXT NOT NULL,
    title        TEXT NOT NULL DEFAULT '主治医师',
    specialty    TEXT,
    intro        TEXT,
    is_active    BOOLEAN NOT NULL DEFAULT 1,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (department) REFERENCES departments(name) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_doctors_department ON doctors(department);
CREATE INDEX IF NOT EXISTS idx_doctors_active ON doctors(is_active);

-- 3. 排班表（v2：加 version 乐观锁 + updated_at + is_holiday）
CREATE TABLE IF NOT EXISTS schedules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id       INTEGER NOT NULL,
    schedule_date   DATE NOT NULL,
    time_slot       TEXT NOT NULL
                        CHECK (time_slot IN ('morning', 'afternoon', 'evening')),
    start_time      TIME NOT NULL,
    end_time        TIME NOT NULL,
    capacity        INTEGER NOT NULL DEFAULT 20,
    remaining       INTEGER NOT NULL DEFAULT 20,
    is_available    BOOLEAN NOT NULL DEFAULT 1,
    is_holiday      BOOLEAN NOT NULL DEFAULT 0,   -- v2: 节假日标记
    version         INTEGER NOT NULL DEFAULT 0,   -- v2: 乐观锁版本号
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- v2
    FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE,
    UNIQUE (doctor_id, schedule_date, time_slot)
);

CREATE INDEX IF NOT EXISTS idx_schedules_date ON schedules(schedule_date);
CREATE INDEX IF NOT EXISTS idx_schedules_doctor_date ON schedules(doctor_id, schedule_date);
CREATE INDEX IF NOT EXISTS idx_schedules_available ON schedules(is_available, schedule_date, remaining);

-- 4. 患者表
CREATE TABLE IF NOT EXISTS patients (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    phone           TEXT,
    insurance_no    TEXT,
    birth_date      DATE,
    gender          TEXT CHECK (gender IN ('M', 'F', 'O')),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_patients_phone ON patients(phone);

-- 5. 预约表（v2：加 idempotency_key 幂等性 + version 乐观锁）
CREATE TABLE IF NOT EXISTS appointments (
    id              TEXT PRIMARY KEY,
    patient_id      TEXT NOT NULL,
    doctor_id       INTEGER NOT NULL,
    schedule_id     INTEGER NOT NULL,
    schedule_version INTEGER,                    -- v2: 落库时的 schedule 版本（审计用）
    symptoms        TEXT,
    duration        TEXT,
    severity        TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'confirmed', 'cancelled', 'completed', 'no_show')),
    confirmed_at    TIMESTAMP,
    cancelled_at    TIMESTAMP,
    cancelled_reason TEXT,                       -- v2: 取消原因
    idempotency_key TEXT UNIQUE,                 -- v2: 幂等键（防重入）
    notes           TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON UPDATE CASCADE,
    FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE RESTRICT,
    FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_appointments_patient ON appointments(patient_id);
CREATE INDEX IF NOT EXISTS idx_appointments_doctor ON appointments(doctor_id);
CREATE INDEX IF NOT EXISTS idx_appointments_status ON appointments(status);
CREATE INDEX IF NOT EXISTS idx_appointments_schedule ON appointments(schedule_id);
CREATE INDEX IF NOT EXISTS idx_appointments_idempotency ON appointments(idempotency_key);

-- 6. 审计日志表（v2 新增）
-- 记录所有写操作（create / cancel / reschedule / restore / capacity_change）
-- 用于合规、回溯、问题排查
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type      TEXT NOT NULL,                -- 'appointment.create' / 'schedule.update' / ...
    entity_type     TEXT NOT NULL,                -- 'appointment' / 'schedule' / 'doctor'
    entity_id       TEXT NOT NULL,                -- 关联 ID
    actor           TEXT NOT NULL DEFAULT 'system', -- 'patient:xxx' / 'his_webhook' / 'scheduler_bot'
    action          TEXT NOT NULL,                -- 'create' / 'update' / 'cancel' / 'restore'
    before_state    TEXT,                         -- JSON 序列化
    after_state     TEXT,                         -- JSON 序列化
    metadata        TEXT,                         -- JSON：额外信息（reason, source, request_id）
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);

-- 7. 上游变更通知表（v2：替代内存 pub/sub）
-- HIS 系统推过来的变更，先入这里，Agent 落库前查
CREATE TABLE IF NOT EXISTS upstream_changes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,                -- 'his' / 'doctor_self' / 'ops'
    entity_type     TEXT NOT NULL,                -- 'schedule' / 'doctor'
    entity_id       TEXT NOT NULL,
    change_type     TEXT NOT NULL,                -- 'delete' / 'update' / 'create'
    new_state       TEXT,                         -- JSON
    applied         BOOLEAN NOT NULL DEFAULT 0,  -- 是否已被 Agent 看到/处理
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_upstream_entity ON upstream_changes(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_upstream_applied ON upstream_changes(applied, created_at);
