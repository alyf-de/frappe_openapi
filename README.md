### Frappe OpenAPI

Dynamic OpenAPI spec for Frappe Framework apps

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app frappe_openapi
```

### Usage

After installing the app, open Swagger UI at `/swagger` to browse the current
site interactively. The Swagger sidebar loads the dynamic OpenAPI tree lazily,
so it is useful for exploring installed apps, modules, **DocTypes**, and
whitelisted methods without generating files first.

The generic dynamic OpenAPI JSON is available at `/openapi.json`. Use this when
you need the current site's generic Frappe API shape, or follow the linked
dynamic documents under `/openapi/...` for app, module, **DocType**, schema, and
method-specific views.

### Generated specs

Generated specs are bundled, SDK-friendly OpenAPI documents written for a
specific site. Generate them with the bench command:

```bash
bench --site mysite generate-openapi --app my_app
```

Use `--app` more than once to generate selected app bundles, or use `--all-apps`
to generate bundles for every installed app. By default, artifacts are written
under the site's private OpenAPI directory. Use `--output ./openapi` when you
want to export the manifest and app bundles to another directory for SDK
generation or publication.

The generated routes are:

- `/openapi/generated/manifest.json`
- `/openapi/generated/apps/{app}.json`

Generated routes are authenticated by default and intended for internal site
documentation unless you explicitly publish the generated files or otherwise
allow public access. Keep internal specs private when they include site-specific
metadata such as Custom Fields or Property Setters.

### User profiles

Frappe OpenAPI supports a few different ways people need to consume API documentation:

- App developers generating a spec for their own app need a stable app-level spec they can ship with their app, publish in their docs, or feed into SDK tooling.
- Organizations hosting public specs for all installed Frappe apps need a browsable catalog that can expose app, module, **DocType**, and method documentation without requiring access to private site data.
- Organizations hosting internal specs for a specific site need site-aware documentation that includes Custom Fields and Property Setters, but is protected like any other internal system documentation.
- Developers browsing someone else's hosted spec need a fast Swagger UI entry point for understanding available resources, fields, and whitelisted methods.
- Developers using someone else's hosted spec with a code generator need a bundled, deterministic OpenAPI document rather than a lazy, multi-document browsing tree.

These profiles imply two complementary outputs:

- Dynamic `/swagger` and `/openapi/...` endpoints for interactive exploration of the current site.
- Generated, bundled app or site specs for SDK generators, publishing, and CI contract checks.

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/frappe_openapi
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade
### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
