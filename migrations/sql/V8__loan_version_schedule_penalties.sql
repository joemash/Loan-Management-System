-- Optimistic locking on loans; penalties on schedules
ALTER TABLE loans ADD COLUMN version BIGINT NOT NULL DEFAULT 0;

ALTER TABLE repayment_schedules ADD COLUMN penalty_accrued NUMERIC(18, 2) NOT NULL DEFAULT 0;
ALTER TABLE repayment_schedules ADD COLUMN penalty_last_accrual_date DATE;
