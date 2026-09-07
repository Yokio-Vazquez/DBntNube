INSERT INTO games (
    title,
    genre,
    classification,
    description,
    release_date
)
VALUES
    (
        'Aetherbound',
        'Aventura',
        'T',
        'Videojuego sintetico de exploracion en un mundo flotante.',
        '2024-05-10'
    ),
    (
        'Circuit Breakers',
        'Estrategia',
        'E10+',
        'Videojuego sintetico de estrategia y gestion de recursos.',
        '2023-11-22'
    ),
    (
        'Neon Drift',
        'Carreras',
        'E',
        'Videojuego sintetico de carreras urbanas futuristas.',
        '2025-02-14'
    ),
    (
        'Titanfall Echoes',
        'Accion',
        'T',
        'Produccion AAA sintetica para consola sobre pilotos y combates mecanizados.',
        '2025-03-21'
    ),
    (
        'Kingdoms of Ember',
        'Rol',
        'T',
        'Produccion AAA sintetica para consola con exploracion, combate y decisiones narrativas.',
        '2024-10-18'
    ),
    (
        'Apex Velocity',
        'Carreras',
        'E',
        'Juego AAA sintetico de carreras para consola con circuitos urbanos y vehiculos de alto rendimiento.',
        '2025-06-27'
    ),
    (
        'Starlight Command',
        'Estrategia',
        'E10+',
        'Produccion AAA sintetica para consola centrada en estrategia espacial y administracion de flotas.',
        '2023-09-15'
    ),
    (
        'Shadow District',
        'Accion',
        'M',
        'Juego AAA sintetico para consola de accion y sigilo ambientado en una ciudad futurista.',
        '2024-02-09'
    ),
    (
        'Mythic Realms',
        'Aventura',
        'E10+',
        'Produccion AAA sintetica para consola con cooperacion, exploracion y mundos fantasticos.',
        '2025-11-07'
    )
ON CONFLICT (title) DO NOTHING;

INSERT INTO game_metrics (
    external_id,
    game_id,
    metric_name,
    metric_value,
    unit,
    measured_at
)
SELECT
    metrics.external_id,
    games.id,
    metrics.metric_name,
    metrics.metric_value,
    metrics.unit,
    metrics.measured_at
FROM (
    VALUES
        ('metric-aetherbound-duration', 'Aetherbound', 'duration', 42.50::numeric, 'hours', '2026-09-06T10:00:00Z'::timestamptz),
        ('metric-aetherbound-rating', 'Aetherbound', 'rating', 4.60::numeric, 'stars', '2026-09-06T10:05:00Z'::timestamptz),
        ('metric-circuit-breakers-duration', 'Circuit Breakers', 'duration', 18.00::numeric, 'hours', '2026-09-06T10:10:00Z'::timestamptz),
        ('metric-circuit-breakers-rating', 'Circuit Breakers', 'rating', 4.10::numeric, 'stars', '2026-09-06T10:15:00Z'::timestamptz),
        ('metric-neon-drift-duration', 'Neon Drift', 'duration', 12.50::numeric, 'hours', '2026-09-06T10:20:00Z'::timestamptz),
        ('metric-neon-drift-rating', 'Neon Drift', 'rating', 3.80::numeric, 'stars', '2026-09-06T10:25:00Z'::timestamptz),
        ('metric-titanfall-echoes-duration', 'Titanfall Echoes', 'duration', 28.00::numeric, 'hours', '2026-09-06T10:30:00Z'::timestamptz),
        ('metric-titanfall-echoes-rating', 'Titanfall Echoes', 'rating', 4.40::numeric, 'stars', '2026-09-06T10:35:00Z'::timestamptz),
        ('metric-kingdoms-of-ember-duration', 'Kingdoms of Ember', 'duration', 64.50::numeric, 'hours', '2026-09-06T10:40:00Z'::timestamptz),
        ('metric-kingdoms-of-ember-rating', 'Kingdoms of Ember', 'rating', 4.80::numeric, 'stars', '2026-09-06T10:45:00Z'::timestamptz),
        ('metric-apex-velocity-duration', 'Apex Velocity', 'duration', 22.00::numeric, 'hours', '2026-09-06T10:50:00Z'::timestamptz),
        ('metric-apex-velocity-rating', 'Apex Velocity', 'rating', 4.30::numeric, 'stars', '2026-09-06T10:55:00Z'::timestamptz),
        ('metric-starlight-command-duration', 'Starlight Command', 'duration', 35.75::numeric, 'hours', '2026-09-06T11:00:00Z'::timestamptz),
        ('metric-starlight-command-rating', 'Starlight Command', 'rating', 4.20::numeric, 'stars', '2026-09-06T11:05:00Z'::timestamptz),
        ('metric-shadow-district-duration', 'Shadow District', 'duration', 19.25::numeric, 'hours', '2026-09-06T11:10:00Z'::timestamptz),
        ('metric-shadow-district-rating', 'Shadow District', 'rating', 4.50::numeric, 'stars', '2026-09-06T11:15:00Z'::timestamptz),
        ('metric-mythic-realms-duration', 'Mythic Realms', 'duration', 48.00::numeric, 'hours', '2026-09-06T11:20:00Z'::timestamptz),
        ('metric-mythic-realms-rating', 'Mythic Realms', 'rating', 4.70::numeric, 'stars', '2026-09-06T11:25:00Z'::timestamptz)
) AS metrics(external_id, title, metric_name, metric_value, unit, measured_at)
JOIN games ON games.title = metrics.title
ON CONFLICT (external_id) DO NOTHING;