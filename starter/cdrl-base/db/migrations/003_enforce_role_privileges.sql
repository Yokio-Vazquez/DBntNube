REVOKE ALL ON SCHEMA public FROM cdrl_writer, cdrl_reader, cdrl_operator;
GRANT USAGE ON SCHEMA public TO cdrl_writer, cdrl_reader;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM cdrl_writer;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM cdrl_writer;

DO $$
BEGIN
    IF to_regclass('public.games') IS NOT NULL THEN
        EXECUTE 'GRANT INSERT, UPDATE ON TABLE public.games TO cdrl_writer';
    END IF;
    IF to_regclass('public.game_metrics') IS NOT NULL THEN
        EXECUTE 'GRANT INSERT, UPDATE ON TABLE public.game_metrics TO cdrl_writer';
    END IF;
    IF to_regclass('public.games_id_seq') IS NOT NULL THEN
        EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE public.games_id_seq TO cdrl_writer';
    END IF;
    IF to_regclass('public.game_metrics_id_seq') IS NOT NULL THEN
        EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE public.game_metrics_id_seq TO cdrl_writer';
    END IF;
    IF to_regclass('public.alembic_version') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE public.alembic_version OWNER TO cdrl_migrator';
    END IF;
END
$$;

ALTER DEFAULT PRIVILEGES FOR ROLE cdrl_migrator IN SCHEMA public
    REVOKE ALL ON TABLES FROM cdrl_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE cdrl_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO cdrl_writer;