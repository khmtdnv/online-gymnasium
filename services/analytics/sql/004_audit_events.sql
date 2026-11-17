CREATE TABLE IF NOT EXISTS audit_events_v1
(
    event_id UUID,
    occurred_at DateTime64(6, 'UTC'),
    event_source LowCardinality(String),
    event_type LowCardinality(String),
    actor_source LowCardinality(String),
    actor_id String,
    envelope_json String,
    student_id Nullable(UUID),
    class_id Nullable(UInt32),
    subject_id Nullable(UInt32),
    answer_id Nullable(UInt32),
    review_status Nullable(String),
    grade Nullable(UInt8)
)
ENGINE = ReplacingMergeTree
ORDER BY event_id;
