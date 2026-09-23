# Autenticação — M9.0

O M9.0 protege a interface web e as APIs do Super Chat antes de qualquer exposição fora de uma rede confiável. O modelo inicial é **single-admin self-hosted**: um único usuário administrativo configurado por ambiente, sem provedor de identidade externo.

## Modelo de segurança

- a senha nunca é armazenada em texto puro;
- `AUTH_PASSWORD_HASH` usa PBKDF2-SHA256 com salt aleatório;
- o token de sessão é opaco e aleatório;
- somente `SHA-256(token)` é persistido em `auth_sessions`;
- o token CSRF também é aleatório e somente seu hash é persistido;
- o cookie de sessão é `HttpOnly` e `SameSite=Strict`;
- o cookie CSRF é `SameSite=Strict` e vinculado à sessão server-side;
- requisições mutáveis sem CSRF válido são rejeitadas;
- `Sec-Fetch-Site: cross-site` é rejeitado em métodos mutáveis;
- logout revoga a sessão no banco antes de apagar os cookies;
- sessões expiram server-side mesmo que um cookie antigo ainda exista.

## Desenvolvimento

Por compatibilidade com testes e desenvolvimento local, o default é:

```env
ENVIRONMENT=development
AUTH_ENABLED=false
```

Nesse modo não há autenticação e a aplicação deve permanecer restrita ao host/rede de desenvolvimento.

## Produção

`ENVIRONMENT=production` é fail-closed. A API não inicia quando alguma destas condições não é atendida:

```env
ENVIRONMENT=production
AUTH_ENABLED=true
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=<pbkdf2_sha256$...>
AUTH_COOKIE_SECURE=true
```

`AUTH_COOKIE_SECURE=true` pressupõe acesso por HTTPS. Não exponha a aplicação em produção somente por HTTP.

## Gerar o hash da senha

Execute localmente, fora de logs e arquivos versionados:

```bash
python scripts/generate_password_hash.py
```

O script solicita a senha duas vezes via `getpass` e imprime apenas o hash PBKDF2-SHA256. Copie esse valor para o `.env` privado como `AUTH_PASSWORD_HASH`.

O repositório público nunca deve conter o hash real usado pela instalação, ainda que o hash não seja a senha em claro.

## Sessões

Configuração padrão:

```env
AUTH_SESSION_TTL_SECONDS=43200
AUTH_COOKIE_NAME=superchat_session
AUTH_CSRF_COOKIE_NAME=superchat_csrf
```

O TTL padrão é 12 horas. O servidor atualiza `last_seen_at` de forma limitada para não gravar no banco em toda requisição.

## Rotas

- `GET /login` — tela de login;
- `POST /auth/login` — autenticação e emissão de sessão;
- `GET /auth/status` — status mínimo da sessão;
- `POST /auth/logout` — revogação da sessão;
- `GET /health` — único health check público e mínimo.

Com `AUTH_ENABLED=true`, `/app`, OpenAPI e endpoints operacionais exigem sessão válida. Acesso HTML não autenticado é redirecionado para `/login`; API não autenticada retorna `401`.

## Limites intencionais do M9.0

Ainda não há:

- múltiplos usuários;
- MFA;
- OAuth/OIDC/SSO;
- recuperação de senha por e-mail;
- RBAC granular;
- gestão de usuários pela interface.

Esses itens devem ser tratados em marcos separados, sem enfraquecer o comportamento fail-closed de produção.
