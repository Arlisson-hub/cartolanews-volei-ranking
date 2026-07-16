<?php
declare(strict_types=1);

/**
 * GitHub Actions helper: baixa feeds JSON cuja reutilização foi autorizada,
 * valida o contrato CNVH e publica arquivos estáveis para o WordPress.
 * Não raspa HTML nem contorna robots.txt, autenticação ou bloqueios.
 */
$root = dirname(__DIR__);
$output = $root . '/generated-rankings';
if (!is_dir($output) && !mkdir($output, 0775, true) && !is_dir($output)) {
    throw new RuntimeException('Não foi possível criar generated-rankings.');
}

foreach (['male' => 'CNVH_RANKING_MALE_URL', 'female' => 'CNVH_RANKING_FEMALE_URL'] as $gender => $variable) {
    $url = trim((string) getenv($variable));
    if ($url === '') { fwrite(STDOUT, "{$variable} não configurada; mantendo arquivo existente.\n"); continue; }
    if (!str_starts_with($url, 'https://')) throw new RuntimeException("{$variable} deve usar HTTPS.");
    $context = stream_context_create(['http' => ['timeout' => 25, 'header' => "Accept: application/json\r\nUser-Agent: CNVH-GitHub-Feed/1.0\r\n"]]);
    $body = @file_get_contents($url, false, $context);
    if (!is_string($body) || $body === '') throw new RuntimeException("Falha ao baixar {$gender}.");
    $data = json_decode($body, true, flags: JSON_THROW_ON_ERROR);
    if (($data['version'] ?? '') !== '1.0' || ($data['type'] ?? '') !== 'official_ranking' || ($data['gender'] ?? '') !== $gender || empty($data['teams']) || !is_array($data['teams'])) {
        throw new RuntimeException("Contrato inválido no feed {$gender}.");
    }
    foreach ($data['teams'] as $team) {
        if (empty($team['rank']) || empty($team['name']) || !isset($team['points'])) throw new RuntimeException("Equipe inválida no feed {$gender}.");
    }
    $json = json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n";
    file_put_contents($output . '/' . $gender . '.json', $json, LOCK_EX);
    fwrite(STDOUT, "Feed {$gender}: " . count($data['teams']) . " equipes.\n");
}

