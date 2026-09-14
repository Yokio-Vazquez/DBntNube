INSERT INTO platforms (code, name, manufacturer)
VALUES
    ('ps5', 'PlayStation 5', 'Sony'),
    ('xbox-series', 'Xbox Series X|S', 'Microsoft'),
    ('switch', 'Nintendo Switch', 'Nintendo')
ON CONFLICT (code) DO NOTHING;

INSERT INTO game_platforms (game_id, platform_id, release_date, status)
SELECT games.id, platforms.id, links.release_date::date, links.status
FROM (
    VALUES
        ('Aetherbound', 'ps5', '2024-05-10', 'available'),
        ('Aetherbound', 'switch', '2024-06-14', 'available'),
        ('Circuit Breakers', 'xbox-series', '2023-11-22', 'available'),
        ('Neon Drift', 'ps5', '2025-02-14', 'available'),
        ('Neon Drift', 'xbox-series', '2025-02-14', 'available'),
        ('Titanfall Echoes', 'ps5', '2025-03-21', 'available'),
        ('Kingdoms of Ember', 'ps5', '2024-10-18', 'available'),
        ('Kingdoms of Ember', 'xbox-series', '2024-10-18', 'available'),
        ('Apex Velocity', 'xbox-series', '2025-06-27', 'available'),
        ('Starlight Command', 'switch', '2023-09-15', 'available'),
        ('Shadow District', 'ps5', '2024-02-09', 'available'),
        ('Mythic Realms', 'switch', '2025-11-07', 'planned')
) AS links(title, platform_code, release_date, status)
JOIN games ON games.title = links.title
JOIN platforms ON platforms.code = links.platform_code
ON CONFLICT (game_id, platform_id) DO NOTHING;

INSERT INTO metric_definitions (metric_name, unit, description)
VALUES
    ('duration', 'hours', 'Horas estimadas de juego'),
    ('rating', 'stars', 'Calificacion promedio de usuarios')
ON CONFLICT (metric_name) DO NOTHING;
