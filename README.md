# authentik en AWS: demo con CloudFormation

Templates y scripts de la charla "authentik en AWS" del AWS Community Day Paraguay 2026. El paso a paso completo, con capturas y los errores que me encontré, está en el post: [ENLACE AL POST].

Con esto desplegás [authentik](https://goauthentik.io) en tu cuenta de AWS (ECS Fargate, RDS PostgreSQL y un Application Load Balancer) y una app de ejemplo, `whoami`, protegida con la acción `authenticate-oidc` del ALB usando authentik como proveedor OpenID. La integración con IAM Identity Center (SAML y SCIM) se configura en las consolas y está explicada en el post.

> **Es una demo, no una instalación para producción.** Usa una sola zona de disponibilidad, no tiene NAT ni backups, y al borrar el stack se borra todo, base de datos incluida. Si solo querés probar authentik, [Docker Compose](https://docs.goauthentik.io/install-config/install/docker-compose/) es más sencillo. Para producción en AWS, partí del [template oficial](https://docs.goauthentik.io/install-config/install/aws/).

## Archivos

| Archivo | Qué es |
| --- | --- |
| `authentik-demo.yaml` | Variante mínima del template oficial de authentik. |
| `whoami-demo.yaml` | Stack aparte con la app `whoami` y la regla `authenticate-oidc` en el listener HTTPS del ALB de authentik. El código de la app va dentro del template. |
| `deploy-authentik.sh` | Crea o actualiza el stack de authentik con los valores de `.env`. |
| `deploy-whoami.sh` | Busca los recursos del stack de authentik (cluster, VPC, subredes, security group, listener) y despliega `whoami` con ellos. |
| `.env.example` | Las variables que usan los scripts. |

## Diferencias con el template oficial

| | Oficial | Esta demo |
| --- | --- | --- |
| Base de datos | `db.m5.large`, Multi-AZ | `db.t4g.small`, Single-AZ, sin backups |
| Tareas server / worker | 2 / 2 | 1 / 1 |
| NAT Gateway | 1 | ninguno: las tareas van en subredes públicas y su security group solo acepta tráfico del ALB |
| Al borrar el stack | RDS deja snapshot, EFS y logs se conservan | se borra todo |
| Logs | sin vencimiento | 3 días |

Las dos variantes se conectan a PostgreSQL con TLS (`AUTHENTIK_POSTGRESQL__SSLMODE=require`). En el template oficial eso está desde authentik 2026.8.4 ([goauthentik/authentik#26807](https://github.com/goauthentik/authentik/pull/26807)); con una versión anterior del oficial, RDS rechaza la conexión.

## Requisitos

- Una cuenta de AWS y la [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) configurada con permisos para crear los recursos.
- Un dominio donde puedas crear registros DNS. Vas a usar dos nombres, por ejemplo `auth.example.com` para authentik y `app.example.com` para `whoami`.
- Un certificado de ACM en la **misma región** donde despliegues, en estado *Issued*, que cubra los dos nombres. Si la validación falla con `CAA_ERROR`, agregá a tu dominio un registro CAA `0 issue "amazon.com"`.

## Pasos

1. Copiá las variables y completalas:

   ```sh
   cp .env.example .env
   ```

   Para el primer stack alcanza con `CERT_ARN` y `AUTHENTIK_HOST`.

2. Desplegá authentik:

   ```sh
   ./deploy-authentik.sh
   ```

   Con `PREVIEW=1 ./deploy-authentik.sh` creás el change set sin ejecutarlo, para ver qué va a cambiar.

3. Creá un CNAME de `AUTHENTIK_HOST` al valor `LoadBalancerDNS` que muestra el script. Si tu DNS está en Cloudflare, dejalo como *DNS only*. Después entrá a `https://AUTHENTIK_HOST/if/flow/initial-setup/` y creá la contraseña de `akadmin`. Hacelo enseguida: hasta que lo hagas, cualquiera que llegue a esa URL puede hacerlo.

4. En authentik, creá una aplicación con slug `whoami` y un provider OAuth2/OpenID, como explica la [guía de la integración con AWS ALB](https://integrations.goauthentik.io/cloud-providers/aws-alb/):
   - Client type: *Confidential*.
   - Redirect URI de tipo *Authorization*, en modo *Strict*: `https://APP_HOST/oauth2/idpresponse`.
   - En *Advanced protocol settings*, desmarcá *Include claims in id_token*.

   Copiá el Client ID y el Client Secret a `CLIENT_ID` y `CLIENT_SECRET` en `.env`, y completá `APP_HOST`.

5. Desplegá `whoami`:

   ```sh
   ./deploy-whoami.sh
   ```

6. Creá un CNAME de `APP_HOST` al mismo `LoadBalancerDNS` y entrá a `https://APP_HOST/`. El ALB te manda a authentik y, después del login, la app muestra tu usuario, los claims del token y los headers que agrega el ALB. Antes de mostrar nada, verifica la firma de `X-Amzn-Oidc-Data` y que `signer`, `iss`, `client` y `exp` sean los esperados.

## Limpieza

Borrá primero `whoami`, porque usa el listener y el security group del ALB de authentik:

```sh
aws cloudformation delete-stack --stack-name demo-authentik-whoami
aws cloudformation wait stack-delete-complete --stack-name demo-authentik-whoami
aws cloudformation delete-stack --stack-name demo-authentik
```

Después borrá los registros DNS y, si ya no lo usás, el certificado.

## Licencia

MIT. `authentik-demo.yaml` deriva del template oficial de authentik (`lifecycle/aws/template.yaml`), también MIT. Ver [LICENSE](LICENSE).
