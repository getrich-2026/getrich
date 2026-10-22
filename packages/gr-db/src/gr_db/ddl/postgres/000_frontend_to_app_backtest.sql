-- 旧库升级：把重构前的 frontend schema 拆成 app + backtest。已定稿，不再修改。
--
-- 前缀 000 是有意的：必须先于 001_extensions 执行 —— 001 会建空的 app schema，
-- 之后再跑本文件就不会把 frontend 改名，旧数据会被留在 frontend 里。
--
-- 三步都先探测再执行，全新的库或已是新结构的库上什么都不做，只记一条账。
-- 不写 BEGIN/COMMIT：runner 把本文件与记账放在同一事务里，自带 COMMIT 会提前提交。
--
-- 旧库执行前先备份：pg_dump -Fc -d getrich > getrich-before-schema-split.dump
--
-- 之后应用侧的连接池 search_path 会变成 app,market,meta,public，
-- 回测相关 SQL 显式写 backtest. 前缀。

-- 1) frontend -> app（整体改名，保留所有对象、索引、约束与数据）
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'frontend')
       AND NOT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'app')
    THEN
        EXECUTE 'ALTER SCHEMA frontend RENAME TO app';
        RAISE NOTICE 'renamed schema frontend -> app';
    ELSE
        RAISE NOTICE 'skip rename: frontend missing or app already exists';
    END IF;
END $$;

-- 2) 回测产物表从 app 移到 backtest
CREATE SCHEMA IF NOT EXISTS backtest;

DO $$
DECLARE
    t text;
    moved int := 0;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'backtest_runs',
        'backtest_metrics',
        'backtest_equity_points',
        'backtest_final_positions',
        'backtest_artifacts',
        'backtest_sweeps',
        'backtest_sweep_trials',
        'backtest_walk_forwards',
        'backtest_walk_forward_windows',
        'backtest_jobs'
    ]
    LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'app' AND table_name = t
        ) THEN
            EXECUTE format('ALTER TABLE app.%I SET SCHEMA backtest', t);
            moved := moved + 1;
        END IF;
    END LOOP;
    RAISE NOTICE 'moved % backtest table(s) app -> backtest', moved;
END $$;

-- 3) 旧的记账表（frontend.schema_migrations，按 prefix 记账）已经不再使用。
--    新记账表是 ops.schema_migrations（按 file_name + checksum）。
--    这里不删除旧表，保留作为审计痕迹；确认无用后可手动 DROP。
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'app' AND table_name = 'schema_migrations'
    ) THEN
        EXECUTE 'ALTER TABLE app.schema_migrations RENAME TO schema_migrations_legacy_prefix';
        RAISE NOTICE 'kept legacy ledger as app.schema_migrations_legacy_prefix';
    END IF;
END $$;
