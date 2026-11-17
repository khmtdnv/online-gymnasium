CREATE TABLE IF NOT EXISTS lesson_snapshots_v2
(
    event_id UInt64,
    occurred_at DateTime64(3, 'UTC'),
    lesson_id UInt64,
    class_id UInt64,
    teacher_id UUID,
    subject_id UInt64,
    starts_at DateTime64(3, 'UTC'),
    ends_at DateTime64(3, 'UTC'),
    status String,
    version UInt64
)
ENGINE = MergeTree
ORDER BY (lesson_id, version, event_id);
