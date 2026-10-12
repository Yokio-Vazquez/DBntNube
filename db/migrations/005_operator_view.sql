-- 005_operator_view.sql
-- Crea la vista operacional segura v_operational_summary que el rol
-- cdrl_operator puede consultar sin acceder directamente a tablas de negocio.
-- El owner de la vista es cdrl_migrator (DDL owner del esquema).

DO $$
BEGIN
    IF to_regclass('public.game_metrics') IS NOT NULL
       AND to_regclass('public.games') IS NOT NULL THEN

        EXECUTE '
            CREATE OR REPLACE VIEW public.v_operational_summary AS
            SELECT
                g.id            AS game_id,
                g.title         AS game_title,
                COUNT(gm.id)    AS total_metrics,
                MAX(gm.measured_at) AS last_measured_at,
                SUM(CASE WHEN gm.deleted_at IS NULL THEN 0 ELSE 1 END)
                                AS soft_deleted_count
            FROM public.games g
            LEFT JOIN public.game_metrics gm ON gm.game_id = g.id
            GROUP BY g.id, g.title
            ORDER BY g.id
        ';

        EXECUTE 'ALTER VIEW public.v_operational_summary OWNER TO cdrl_migrator';

        -- El operador puede consultar la vista pero NO las tablas base
        EXECUTE 'GRANT SELECT ON public.v_operational_summary TO cdrl_operator';

    END IF;
END
$$;
