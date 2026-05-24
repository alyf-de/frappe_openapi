const csrfToken = document.querySelector("meta[name='x-frappe-csrf-token']")?.content;
const navSections = document.querySelector("#frappe-openapi-nav-sections");
const navError = document.querySelector("#frappe-openapi-nav-error");
const overview = document.querySelector("#frappe-openapi-overview");
const swagger = document.querySelector("#swagger-ui");
const filterInput = document.querySelector("#frappe-openapi-filter");
const filterStatus = document.querySelector("#frappe-openapi-filter-status");

const SEARCH_INDEX_URL = "/openapi/search-index.json";
const GENERATED_MANIFEST_URL = "/openapi/generated/manifest.json";
const MAX_SEARCH_RESULTS = 50;
const appIndexCache = new Map();
const moduleIndexCache = new Map();
const doctypeIndexCache = new Map();
let searchIndexCache = null;
let generatedManifestCache = null;
let currentFilterQuery = "";

const searchResults = document.createElement("div");
searchResults.id = "frappe-openapi-search-results";
searchResults.className = "frappe-openapi-search-results";
searchResults.hidden = true;
filterStatus.insertAdjacentElement("afterend", searchResults);

navSections.setAttribute("aria-busy", "true");

function sortedEntries(value) {
	return Object.entries(value || {}).sort(([left], [right]) => left.localeCompare(right));
}

function normalizeSearchText(value) {
	return String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function matchesSearchQuery(text, query) {
	const normalizedQuery = normalizeSearchText(query);
	if (!normalizedQuery) {
		return true;
	}
	const normalizedText = normalizeSearchText(text);
	return normalizedQuery.split(" ").every((part) => normalizedText.includes(part));
}

function normalizeInternalSpecUrl(url) {
	const parsed = new URL(url, window.location.origin);
	if (parsed.pathname === "/openapi.json" || parsed.pathname.startsWith("/openapi/")) {
		return `${parsed.pathname}${parsed.search}${parsed.hash}`;
	}
	return url;
}

async function fetchSpec(url) {
	url = normalizeInternalSpecUrl(url);
	const response = await fetch(url, { credentials: "same-origin" });
	if (!response.ok) {
		throw new Error(`Could not load ${url}. Check that the document exists and try again.`);
	}
	return response.json();
}

async function fetchAppIndex(app, url) {
	if (!appIndexCache.has(app)) {
		appIndexCache.set(app, fetchSpec(url));
	}
	return appIndexCache.get(app);
}

async function fetchModuleIndex(url) {
	url = normalizeInternalSpecUrl(url);
	if (!moduleIndexCache.has(url)) {
		moduleIndexCache.set(url, fetchSpec(url));
	}
	return moduleIndexCache.get(url);
}

async function fetchDocTypeIndex(url) {
	url = normalizeInternalSpecUrl(url);
	if (!doctypeIndexCache.has(url)) {
		doctypeIndexCache.set(url, fetchSpec(url));
	}
	return doctypeIndexCache.get(url);
}

async function fetchSearchIndex() {
	if (!searchIndexCache) {
		searchIndexCache = fetchSpec(SEARCH_INDEX_URL);
	}
	return searchIndexCache;
}

async function fetchGeneratedManifest() {
	if (!generatedManifestCache) {
		generatedManifestCache = fetch(GENERATED_MANIFEST_URL, { credentials: "same-origin" })
			.then((response) => response.ok ? response.json() : null)
			.catch(() => null);
	}
	return generatedManifestCache;
}

function documentLinks(document) {
	return document["x-frappe-openapi-documents"] || {};
}

function generatedSpecDocuments(manifest) {
	return sortedEntries(manifest?.apps).map(([app, artifact]) => ({
		kind: "link",
		label: app,
		type: "Generated App",
		url: artifact.url,
		level: 0,
		keywords: `${app} generated bundle sdk openapi`,
	}));
}

function refreshActiveFilter() {
	if (currentFilterQuery) {
		handleFilterInput(currentFilterQuery);
	}
}

function renderStatus(container, message, level, tone) {
	const status = document.createElement("div");
	status.className = `frappe-openapi-nav-status level-${level || 0}${tone ? ` ${tone}` : ""}`;
	status.setAttribute("role", tone === "error" ? "alert" : "status");
	status.textContent = message;
	container.appendChild(status);
	return status;
}

function setGroupLoading(group, loading) {
	group.classList.toggle("is-loading", loading);
	group.setAttribute("aria-busy", loading ? "true" : "false");
}

function clearLazyContent(group) {
	for (const element of Array.from(
		group.querySelectorAll(
			":scope > .frappe-openapi-nav-link, :scope > .frappe-openapi-nav-group, :scope > .frappe-openapi-nav-status"
		)
	)) {
		element.remove();
	}
}

function createSummary(documentEntry) {
	const summary = document.createElement("summary");
	summary.dataset.navEntry = "group";
	summary.dataset.level = documentEntry.level;
	summary.dataset.searchText = `${documentEntry.label} ${documentEntry.type || ""} ${documentEntry.keywords || ""}`;
	if (documentEntry.clickable && documentEntry.url) {
		summary.classList.add("frappe-openapi-nav-summary-link");
		summary.dataset.key = documentEntry.key || keyForUrl(documentEntry.url);
		summary.addEventListener("click", () => {
			loadSpec(documentEntry.url, summary.dataset.key);
		});
	}

	const label = document.createElement("span");
	label.className = "frappe-openapi-nav-label";
	label.textContent = documentEntry.label;
	summary.appendChild(label);

	if (documentEntry.type) {
		const type = document.createElement("span");
		type.className = "frappe-openapi-nav-type";
		type.textContent = documentEntry.type;
		summary.appendChild(type);
	}

	return summary;
}

function renderNavigationLink(documentEntry, sectionElement) {
	const link = document.createElement("a");
	const documentUrl = documentEntry.url ? normalizeInternalSpecUrl(documentEntry.url) : "";
	link.className = `frappe-openapi-nav-link level-${documentEntry.level}`;
	link.href = documentUrl || "#overview";
	link.dataset.key = documentEntry.key || (documentUrl ? keyForUrl(documentUrl) : "overview");
	link.dataset.navEntry = "link";
	link.dataset.level = documentEntry.level;
	link.dataset.searchText = `${documentEntry.label} ${documentEntry.type || ""} ${documentEntry.keywords || ""}`;
	link.addEventListener("click", (event) => {
		event.preventDefault();
		if (documentEntry.kind === "overview") {
			showOverview();
		} else {
			loadSpec(documentUrl, link.dataset.key);
		}
	});

	const label = document.createElement("span");
	label.className = "frappe-openapi-nav-label";
	label.textContent = documentEntry.label;

	const type = document.createElement("span");
	type.className = "frappe-openapi-nav-type";
	type.textContent = documentEntry.type;

	link.append(label, type);
	sectionElement.appendChild(link);
	return link;
}

function renderStaticGroup(documentEntry, sectionElement, open = false) {
	const group = document.createElement("details");
	group.className = `frappe-openapi-nav-group level-${documentEntry.level}`;
	group.dataset.defaultOpen = open ? "true" : "false";
	group.dataset.loaded = "true";
	group.open = open;
	group.appendChild(createSummary(documentEntry));
	sectionElement.appendChild(group);
	return group;
}

function renderLazyGroup(documentEntry, sectionElement, onOpen) {
	const group = document.createElement("details");
	group.className = `frappe-openapi-nav-group level-${documentEntry.level}`;
	group.dataset.defaultOpen = "false";
	group.appendChild(createSummary(documentEntry));
	group.addEventListener("toggle", () => {
		if (group.open && !group.dataset.loaded && !group.dataset.loading) {
			onOpen(group);
		}
	});
	sectionElement.appendChild(group);
	return group;
}

function renderNavigationEntry(documentEntry, sectionElement) {
	if (documentEntry.kind === "overview" || documentEntry.kind === "link") {
		renderNavigationLink(documentEntry, sectionElement);
	} else if (documentEntry.kind === "app") {
		renderLazyGroup(documentEntry, sectionElement, (group) => {
			loadAppDetails(group, documentEntry.app, documentEntry.url);
		});
	}
}

async function buildNavigation() {
	const index = await fetchSpec("/openapi.json");
	const generatedManifest = await fetchGeneratedManifest();
	const documents = documentLinks(index);
	const apps = sortedEntries(documents.apps);
	const generatedSpecs = generatedSpecDocuments(generatedManifest);
	const genericApiUrl = documents.generic_api_v2 || index.$self || "/openapi.json";
	const primary = [
		{ kind: "overview", label: "Overview", type: "Welcome", level: 0 },
		{
			kind: "link",
			label: "Generic API v2",
			type: "Generic CRUD",
			url: genericApiUrl,
			level: 0,
			keywords: "root overview generic crud documents doctypes",
		},
	];
	if (documents.auth) {
		primary.push({ kind: "link", label: "Auth", type: "Authentication", url: documents.auth, level: 0 });
	}

	return [
		{ title: "Core", documents: primary, open: true },
		{ title: "Generated Specs", documents: generatedSpecs, open: false },
		{
			title: "Apps",
			documents: apps.map(([app, url]) => ({
				kind: "app",
				label: app,
				type: "App",
				app,
				url,
				level: 0,
				keywords: "modules doctypes whitelisted methods",
			})),
			open: false,
		},
	].filter((section) => section.documents.length);
}

function renderMethodLinks(methods, sectionElement, level, keywords = "") {
	for (const [method, methodUrl] of sortedEntries(methods)) {
		renderNavigationLink(
			{
				kind: "link",
				label: method,
				type: "Whitelisted Method",
				url: methodUrl,
				level,
				keywords,
			},
			sectionElement
		);
	}
}

function renderMethodGroup(label, methods, sectionElement, level, keywords = "") {
	if (!Object.keys(methods || {}).length) {
		return null;
	}

	const group = renderStaticGroup(
		{
			label,
			type: "Methods",
			level,
			keywords: `${keywords} whitelisted methods`,
		},
		sectionElement
	);
	renderMethodLinks(methods, group, level + 1, keywords);
	return group;
}

function getDocTypeUrl(doctypeDocument) {
	if (typeof doctypeDocument === "string") {
		return doctypeDocument;
	}
	return doctypeDocument.url;
}

function getDocTypeFileMethods(doctypeDocument) {
	if (typeof doctypeDocument === "string") {
		return {};
	}
	return doctypeDocument.methods || {};
}

async function loadAppDetails(group, app, appUrl) {
	group.dataset.loading = "true";
	setGroupLoading(group, true);
	clearLazyContent(group);
	const loading = renderStatus(group, "Loading app...", 1);
	try {
		const appIndex = await fetchAppIndex(app, appUrl);
		const documents = documentLinks(appIndex);
		const modules = sortedEntries(documents.modules);
		loading.remove();
		renderMethodGroup("App methods", documents.methods, group, 1, app);
		for (const [module, moduleUrl] of modules) {
			renderLazyGroup(
				{
					label: module,
					type: "Module",
					level: 1,
					keywords: `${app} module doctypes methods`,
				},
				group,
				(moduleGroup) => loadModuleDetails(moduleGroup, app, module, moduleUrl)
			);
		}
		if (!Object.keys(documents.methods || {}).length && !modules.length) {
			renderStatus(group, "No methods or modules found for this app.", 1);
		}
		group.dataset.loaded = "true";
		refreshActiveFilter();
	} catch (error) {
		loading.remove();
		renderStatus(group, error.message, 1, "error");
	} finally {
		delete group.dataset.loading;
		setGroupLoading(group, false);
	}
}

async function loadModuleDetails(group, app, module, moduleUrl) {
	group.dataset.loading = "true";
	setGroupLoading(group, true);
	clearLazyContent(group);
	const loading = renderStatus(group, "Loading module...", 2);
	try {
		const moduleIndex = await fetchModuleIndex(moduleUrl);
		const documents = documentLinks(moduleIndex);
		const doctypes = sortedEntries(documents.doctypes);
		loading.remove();
		renderMethodGroup("Module methods", documents.methods, group, 2, `${app} ${module}`);
		for (const [doctype, doctypeDocument] of doctypes) {
			const doctypeUrl = getDocTypeUrl(doctypeDocument);
			const fileMethods = getDocTypeFileMethods(doctypeDocument);
			renderLazyGroup(
				{
					label: doctype,
					type: "DocType",
					url: doctypeUrl,
					clickable: true,
					level: 2,
					keywords: `${app} ${module} crud controller file methods ${Object.keys(fileMethods).length} file methods`,
				},
				group,
				(doctypeGroup) => {
					loadDocTypeDetails(
						doctypeGroup,
						doctype,
						doctypeUrl,
						fileMethods
					);
				}
			);
		}
		if (!Object.keys(documents.methods || {}).length && !doctypes.length) {
			renderStatus(group, "No methods or DocTypes found in this module.", 2);
		}
		group.dataset.loaded = "true";
		refreshActiveFilter();
	} catch (error) {
		loading.remove();
		renderStatus(group, error.message, 2, "error");
	} finally {
		delete group.dataset.loading;
		setGroupLoading(group, false);
	}
}

async function loadDocTypeDetails(group, doctype, doctypeUrl, moduleFileMethods) {
	group.dataset.loading = "true";
	setGroupLoading(group, true);
	clearLazyContent(group);
	const loading = renderStatus(group, "Loading DocType...", 3);
	try {
		const doctypeIndex = await fetchDocTypeIndex(doctypeUrl);
		const fileMethods = documentLinks(doctypeIndex).file_methods || moduleFileMethods;
		const controllerMethods = doctypeIndex["x-frappe-doc-methods"] || [];
		loading.remove();
		renderStatus(group, docTypeDetailSummary(controllerMethods, fileMethods), 3);
		renderMethodGroup("File-level methods", fileMethods, group, 3, doctype);
		group.dataset.loaded = "true";
		refreshActiveFilter();
	} catch (error) {
		loading.remove();
		renderStatus(group, error.message, 3, "error");
	} finally {
		delete group.dataset.loading;
		setGroupLoading(group, false);
	}
}

function docTypeDetailSummary(controllerMethods, fileMethods) {
	const details = ["CRUD operations"];
	if (controllerMethods.length) {
		details.push(`${controllerMethods.length} controller ${pluralize("method", controllerMethods.length)}`);
	}
	const fileMethodCount = Object.keys(fileMethods || {}).length;
	if (fileMethodCount) {
		details.push(`${fileMethodCount} file-level ${pluralize("method", fileMethodCount)}`);
	}
	return `Spec includes ${details.join(", ")}.`;
}

function pluralize(label, count) {
	return count === 1 ? label : `${label}s`;
}

function showOverview() {
	overview.hidden = false;
	swagger.hidden = true;
	setActiveKey("overview");
}

function showSwagger() {
	overview.hidden = true;
	swagger.hidden = false;
}

function keyForUrl(url) {
	return new URL(normalizeInternalSpecUrl(url), window.location.origin).href;
}

function setActiveKey(key) {
	for (const link of document.querySelectorAll(
		".frappe-openapi-nav-link, .frappe-openapi-nav-summary-link, .frappe-openapi-search-result"
	)) {
		const isActive = link.dataset.key === key;
		link.classList.toggle("active", isActive);
		if (isActive) {
			link.setAttribute("aria-current", "page");
		} else {
			link.removeAttribute("aria-current");
		}
	}
}

function setActiveLink(url) {
	setActiveKey(keyForUrl(url));
}

function loadSpec(url, activeKey = keyForUrl(url)) {
	url = normalizeInternalSpecUrl(url);
	showSwagger();
	window.ui.specActions.updateUrl(url);
	window.ui.specActions.download(url);
	setActiveKey(activeKey);
}

function searchIndexItems(index) {
	return index.items || [];
}

function searchIndexText(item) {
	return [
		item.label,
		item.type,
		item.app,
		item.module,
		item.doctype,
		item.method,
		item.keywords,
	].filter(Boolean).join(" ");
}

function matchingSearchResults(index, query) {
	return searchIndexItems(index)
		.filter((item) => matchesSearchQuery(searchIndexText(item), query))
		.slice(0, MAX_SEARCH_RESULTS);
}

function searchResultMetadata(item) {
	return [item.type, item.app, item.module, item.doctype].filter(Boolean).join(" · ");
}

function searchResultKey(item) {
	if (item.type === "Controller Method" && item.method) {
		return `${keyForUrl(item.url)}#controller:${item.method}`;
	}
	return keyForUrl(item.url);
}

function renderSearchResults(results) {
	searchResults.textContent = "";
	searchResults.hidden = !currentFilterQuery || !results.length;
	if (searchResults.hidden) {
		return;
	}

	for (const item of results) {
		const link = document.createElement("a");
		const itemUrl = normalizeInternalSpecUrl(item.url);
		link.className = "frappe-openapi-search-result";
		link.href = itemUrl;
		link.dataset.key = searchResultKey(item);
		link.addEventListener("click", (event) => {
			event.preventDefault();
			loadSpec(itemUrl, link.dataset.key);
		});

		const label = document.createElement("span");
		label.className = "frappe-openapi-nav-label";
		label.textContent = item.label;

		const metadata = document.createElement("span");
		metadata.className = "frappe-openapi-nav-type";
		metadata.textContent = searchResultMetadata(item);

		link.append(label, metadata);
		searchResults.appendChild(link);
	}
}

function renderSearchLoading() {
	searchResults.textContent = "";
	searchResults.hidden = true;
}

function handleFilterInput(query) {
	currentFilterQuery = query;
	const visibleLinks = filterNavigation(query);
	if (!query) {
		renderSearchResults([]);
		updateFilterStatus(query, visibleLinks);
		return;
	}

	renderSearchLoading();
	updateFilterStatus(query, visibleLinks, null, true);
	fetchSearchIndex()
		.then((index) => {
			if (query !== currentFilterQuery) {
				return;
			}
			const results = matchingSearchResults(index, query);
			renderSearchResults(results);
			updateFilterStatus(query, visibleLinks, results.length);
		})
		.catch((error) => {
			if (query !== currentFilterQuery) {
				return;
			}
			renderSearchResults([]);
			updateFilterStatus(query, visibleLinks, null, false, error.message);
		});
}

function filterNavigation(query) {
	const searching = Boolean(query);
	let visibleLinks = 0;
	for (const link of document.querySelectorAll(".frappe-openapi-nav-link")) {
		const matches = matchesSearchQuery(link.dataset.searchText, query);
		link.hidden = searching && !matches;
		if (!link.hidden) {
			visibleLinks += 1;
		}
	}

	const groups = Array.from(
		document.querySelectorAll(".frappe-openapi-nav-section, .frappe-openapi-nav-group")
	).reverse();
	for (const group of groups) {
		const summary = group.querySelector(":scope > summary");
		const selfMatches = summary && matchesSearchQuery(summary.dataset.searchText, query);
		const hasVisibleChild = Array.from(
			group.querySelectorAll(":scope > .frappe-openapi-nav-link, :scope > .frappe-openapi-nav-group")
		).some((entry) => !entry.hidden);

		group.hidden = searching && !selfMatches && !hasVisibleChild;
		if (searching) {
			if (group.classList.contains("frappe-openapi-nav-section") || group.dataset.loaded === "true") {
				group.open = !group.hidden;
			}
		} else {
			group.open = group.dataset.defaultOpen === "true";
		}
	}

	return visibleLinks;
}

function updateFilterStatus(query, visibleLinks, globalResults = null, loading = false, error = "") {
	if (!query) {
		filterStatus.hidden = true;
		filterStatus.textContent = "";
		return;
	}

	filterStatus.hidden = false;
	if (error) {
		filterStatus.textContent = error;
	} else if (loading) {
		filterStatus.textContent = "Searching all OpenAPI documents...";
	} else if (globalResults === 0 && visibleLinks === 0) {
		filterStatus.textContent = "No OpenAPI documents match.";
	} else if (globalResults === 1) {
		filterStatus.textContent = "1 OpenAPI document matches.";
	} else if (globalResults !== null) {
		filterStatus.textContent = `${globalResults} OpenAPI documents match.`;
	} else if (visibleLinks === 1) {
		filterStatus.textContent = "1 loaded document matches.";
	} else {
		filterStatus.textContent = `${visibleLinks} loaded documents match.`;
	}
}

function initializeSwagger() {
	swagger.hidden = true;
	window.ui = SwaggerUIBundle({
		dom_id: "#swagger-ui",
		spec: {
			openapi: "3.2.0",
			info: {
				title: "Select an OpenAPI document",
				version: "",
			},
			paths: {},
		},
		deepLinking: true,
		layout: "StandaloneLayout",
		persistAuthorization: true,
		queryConfigEnabled: true,
		oauth2RedirectUrl: `${window.location.origin}/swagger/oauth2-redirect.html`,
		presets: [
			SwaggerUIBundle.presets.apis,
			SwaggerUIStandalonePreset,
		],
		plugins: [
			SwaggerUIBundle.plugins.DownloadUrl,
		],
		requestInterceptor: (request) => {
			const method = String(request.method || "GET").toUpperCase();
			request.url = normalizeInternalSpecUrl(request.url);
			request.credentials = "same-origin";
			request.headers = request.headers || {};
			if (csrfToken && !["GET", "HEAD", "OPTIONS"].includes(method)) {
				request.headers["X-Frappe-CSRF-Token"] = csrfToken;
			}
			return request;
		},
	});
}

function renderNavigation(sections) {
	navSections.textContent = "";
	navSections.setAttribute("aria-busy", "false");
	for (const section of sections) {
		const sectionElement = document.createElement("details");
		sectionElement.className = "frappe-openapi-nav-section";
		sectionElement.dataset.defaultOpen = section.open ? "true" : "false";
		if (section.open) {
			sectionElement.open = true;
		}

		const heading = document.createElement("summary");
		heading.dataset.navEntry = "group";
		heading.dataset.level = -1;
		heading.dataset.searchText = section.title;
		heading.textContent = section.title;
		sectionElement.appendChild(heading);

		for (const documentEntry of section.documents) {
			renderNavigationEntry(documentEntry, sectionElement);
		}

		navSections.appendChild(sectionElement);
	}

	showOverview();
}

filterInput.addEventListener("input", (event) => {
	const query = event.target.value.trim().toLowerCase();
	handleFilterInput(query);
});

initializeSwagger();

buildNavigation()
	.then(renderNavigation)
	.catch((error) => {
		navSections.setAttribute("aria-busy", "false");
		navError.textContent = error.message;
		navError.style.display = "block";
	});
