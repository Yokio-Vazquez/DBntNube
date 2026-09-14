-- Juegos disponibles en una plataforma con una calificacion minima.
SELECT
    games.title,
    platforms.name AS platform,
    game_platforms.status,
    rating.metric_value AS rating
FROM games
JOIN game_platforms ON game_platforms.game_id = games.id
JOIN platforms ON platforms.id = game_platforms.platform_id
JOIN game_metrics AS rating
    ON rating.game_id = games.id
   AND rating.metric_name = 'rating'
WHERE platforms.code = :platform_code
  AND rating.metric_value >= :minimum_rating
ORDER BY rating.metric_value DESC, games.title;

-- Cobertura de plataformas, incluyendo juegos sin una publicacion asociada.
SELECT
    games.title,
    COUNT(game_platforms.platform_id) AS platform_count
FROM games
LEFT JOIN game_platforms ON game_platforms.game_id = games.id
GROUP BY games.id, games.title
HAVING COUNT(game_platforms.platform_id) BETWEEN :minimum_platforms AND :maximum_platforms
ORDER BY games.title;

-- Metricas de un tipo dentro de un intervalo parametrizado.
SELECT
    games.title,
    game_metrics.metric_value,
    game_metrics.unit,
    game_metrics.measured_at
FROM game_metrics
JOIN games ON games.id = game_metrics.game_id
WHERE game_metrics.metric_name = :metric_name
  AND game_metrics.metric_value BETWEEN :minimum_value AND :maximum_value
ORDER BY game_metrics.metric_value, games.title;
