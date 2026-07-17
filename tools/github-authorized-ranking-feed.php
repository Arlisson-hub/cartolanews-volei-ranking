<?php
declare(strict_types=1);

/**
 * Baixa feeds JSON autorizados, valida o contrato CNVH e publica cópias
 * estáveis para o WordPress. Não raspa HTML nem contorna bloqueios.
 */
$root = dirname(__DIR__);
$output = $root . '/generated-rankings';
$failures = [];
$configured = 0;
$written = 0;

if (!is_dir($output) && !mkdir($output, 0775, true) && !is_dir($output)) {
    fwrite(STDERR, "::error::Não foi possível criar generated-rankings.\n");
    exit(1);
}

foreach (['male' => 'CNVH_RANKING_MALE_URL', 'female' => 'CNVH_RANKING_FEMALE_URL'] as $gender => $variable) {
    $url = trim((string) getenv($variable));
    if ($url === '') {
        fwrite(STDOUT, "::notice::{$variable} não configurada; mantendo arquivo existente.\n");
        continue;
    }

    try {
        $configured++;
        if (!filter_var($url, FILTER_VALIDATE_URL) || !str_starts_with($url, 'https://')) {
            throw new RuntimeException("{$variable} deve conter uma URL HTTPS válida.");
        }

        $context = stream_context_create(['http' => [
            'timeout' => 25,
            'ignore_errors' => true,
            'follow_location' => 1,
            'max_redirects' => 3,
            'header' => "Accept: application/json\r\nUser-Agent: CNVH-GitHub-Feed/1.1\r\n",
        ]]);
        $body = @file_get_contents($url, false, $context);
        $headers = $http_response_header ?? [];
        $status = extract_http_status($headers);
        $contentType = extract_header($headers, 'Content-Type') ?: 'não informado';

        if (!is_string($body) || trim($body) === '') {
            throw new RuntimeException("Resposta vazia ou indisponível (HTTP {$status}).");
        }
        if ($status < 200 || $status >= 300) {
            throw new RuntimeException("A fonte respondeu HTTP {$status}, tipo {$contentType}.");
        }

        try {
            $data = json_decode($body, true, 512, JSON_THROW_ON_ERROR);
        } catch (JsonException $error) {
            $preview = response_preview($body);
            throw new RuntimeException("A URL não retornou JSON válido. Content-Type: {$contentType}. Início da resposta: {$preview}");
        }

        if (!is_array($data) || ($data['version'] ?? '') !== '1.0' || ($data['type'] ?? '') !== 'official_ranking' || ($data['gender'] ?? '') !== $gender || empty($data['teams']) || !is_array($data['teams'])) {
            throw new RuntimeException("JSON recebido, mas fora do contrato CNVH para {$gender}. Verifique version, type, gender e teams.");
        }
        foreach ($data['teams'] as $index => $team) {
            if (!is_array($team) || empty($team['rank']) || empty($team['name']) || !isset($team['points'])) {
                throw new RuntimeException('Equipe inválida no índice ' . $index . ". Campos obrigatórios: rank, name e points.");
            }
        }

        $json = json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n";
        if (file_put_contents($output . '/' . $gender . '.json', $json, LOCK_EX) === false) {
            throw new RuntimeException("Não foi possível gravar generated-rankings/{$gender}.json.");
        }
        fwrite(STDOUT, "Feed {$gender}: " . count($data['teams']) . " equipes validadas.\n");
        $written++;
    } catch (Throwable $error) {
        $host = parse_url($url, PHP_URL_HOST) ?: 'fonte desconhecida';
        $message = "{$variable} ({$host}): " . $error->getMessage();
        $failures[] = $message;
        fwrite(STDERR, "::error::{$message}\n");
    }
}

if ($configured === 0 && !is_file($output . '/male.json') && !is_file($output . '/female.json')) {
    fwrite(STDERR, "::error::Nenhuma URL de origem foi configurada e não existem rankings gerados anteriormente.\n");
    fwrite(STDERR, "Cadastre CNVH_RANKING_MALE_URL e/ou CNVH_RANKING_FEMALE_URL apontando para JSON válido.\n");
    exit(1);
}

if ($failures) {
    fwrite(STDERR, "\nFalha em " . count($failures) . " feed(s). Os arquivos válidos anteriores foram preservados.\n");
    exit(1);
}

fwrite(STDOUT, "Resumo: {$configured} feed(s) configurado(s), {$written} arquivo(s) atualizado(s).\n");

function extract_http_status(array $headers): int {
    $status = 0;
    foreach ($headers as $header) {
        if (preg_match('~^HTTP/\S+\s+(\d{3})~i', $header, $match)) $status = (int) $match[1];
    }
    return $status;
}

function extract_header(array $headers, string $name): string {
    $value = '';
    foreach ($headers as $header) {
        if (stripos($header, $name . ':') === 0) $value = trim(substr($header, strlen($name) + 1));
    }
    return $value;
}

function response_preview(string $body): string {
    $text = trim(preg_replace('/\s+/', ' ', strip_tags($body)) ?? '');
    $text = preg_replace('/[^\p{L}\p{N}\p{P}\p{Z}]/u', '', $text) ?? '';
    $preview = function_exists('mb_substr') ? mb_substr($text, 0, 160) : substr($text, 0, 160);
    return $preview ?: '[conteúdo não textual]';
}
