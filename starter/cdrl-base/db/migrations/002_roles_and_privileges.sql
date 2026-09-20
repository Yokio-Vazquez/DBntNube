\set ON_ERROR_STOP on
\if :{?migrator_password}
\else
\echo 'migrator_password is required'
\quit 1
\endif
\if :{?writer_password}
\else
\echo 'writer_password is required'
\quit 1
\endif
\if :{?reader_password}
\else
\echo 'reader_password is required'
\quit 1
\endif
\if :{?operator_password}
\else
\echo 'operator_password is required'
\quit 1
\endif

SELECT format('CREATE ROLE cdrl_migrator LOGIN PASSWORD %L', :'migrator_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cdrl_migrator')\gexec
ALTER ROLE cdrl_migrator LOGIN PASSWORD :'migrator_password';

SELECT format('CREATE ROLE cdrl_writer LOGIN PASSWORD %L NOINHERIT', :'writer_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cdrl_writer')\gexec
ALTER ROLE cdrl_writer LOGIN PASSWORD :'writer_password' NOINHERIT;

SELECT format('CREATE ROLE cdrl_reader LOGIN PASSWORD %L NOINHERIT', :'reader_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cdrl_reader')\gexec
ALTER ROLE cdrl_reader LOGIN PASSWORD :'reader_password' NOINHERIT;

SELECT format('CREATE ROLE cdrl_operator LOGIN PASSWORD %L NOINHERIT', :'operator_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cdrl_operator')\gexec
ALTER ROLE cdrl_operator LOGIN PASSWORD :'operator_password' NOINHERIT;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO cdrl_migrator;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC;

GRANT USAGE ON SCHEMA public TO cdrl_writer, cdrl_reader;

DO $$
BEGIN
    IF to_regclass('public.games') IS NOT NULL THEN
        EXECUTE 'GRANT INSERT, UPDATE ON TABLE public.games TO cdrl_writer';
        EXECUTE 'REVOKE DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.games FROM cdrl_writer';
    END IF;
    IF to_regclass('public.game_metrics') IS NOT NULL THEN
        EXECUTE 'GRANT INSERT, UPDATE ON TABLE public.game_metrics TO cdrl_writer';
        EXECUTE 'REVOKE DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.game_metrics FROM cdrl_writer';
    END IF;
    IF to_regclass('public.games_id_seq') IS NOT NULL THEN
        EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE public.games_id_seq TO cdrl_writer';
    END IF;
    IF to_regclass('public.game_metrics_id_seq') IS NOT NULL THEN
        EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE public.game_metrics_id_seq TO cdrl_writer';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO cdrl_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cdrl_reader;

-- operator may connect and inspect PostgreSQL health, but cannot read business tables.
GRANT pg_monitor TO cdrl_operator;

ALTER DEFAULT PRIVILEGES FOR ROLE cdrl_migrator IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE cdrl_migrator IN SCHEMA public GRANT SELECT ON TABLES TO cdrl_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE cdrl_migrator IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC;

DO $$
DECLARE
    object_name text;
BEGIN
    FOREACH object_name IN ARRAY ARRAY[
        'games', 'game_metrics', 'platforms', 'game_platforms', 'metric_definitions'
    ] LOOP
        IF to_regclass(format('public.%s', object_name)) IS NOT NULL THEN
            EXECUTE format('ALTER TABLE public.%I OWNER TO cdrl_migrator', object_name);
        END IF;
    END LOOP;
END
$$;