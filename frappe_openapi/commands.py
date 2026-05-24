from pathlib import Path

import click
import frappe
from frappe.commands import pass_context
from frappe.exceptions import SiteNotSpecifiedError
from frappe.utils.bench_helper import CliCtxObj

from frappe_openapi.generator import generate_app_bundles
from frappe_openapi.registry import get_installed_apps


@click.command("generate-openapi")
@click.option("--app", "apps", multiple=True, help="Generate a bundle for this app. Can be used more than once.")
@click.option("--all-apps", is_flag=True, default=False, help="Generate bundles for all installed apps.")
@click.option(
	"--output",
	type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
	help="Directory for generated artifacts. Defaults to the current site's private/openapi directory.",
)
@pass_context
def generate_openapi(context: CliCtxObj, apps: tuple[str, ...], all_apps: bool = False, output: Path | None = None):
	"Generate site-aware OpenAPI bundles for SDKs and publication."
	if not context.sites:
		raise SiteNotSpecifiedError

	if apps and all_apps:
		raise click.ClickException("Use either --app or --all-apps, not both.")

	for site in context.sites:
		frappe.init(site)
		frappe.connect()
		try:
			selected_apps = list(get_installed_apps()) if all_apps or not apps else list(apps)
			result = generate_app_bundles(selected_apps, output=output)
			click.echo(f"Generated {len(result['apps'])} OpenAPI app bundle(s) for {site}.")
			click.echo(f"Manifest: {result['manifest_path']}")
		except ValueError as exc:
			raise click.ClickException(str(exc))
		finally:
			frappe.destroy()


commands = [
	generate_openapi,
]
