//console.log("🔥 resource_center.js chargé - version test 2026-04-29-frontend");
window.RESSOURCE_DEBUG_LOADED = true;

(function () {
  "use strict";

  const RESSOURCE_ROOT_SELECTOR = "#ressource-center-page";
  const MAX_RESULTS = 20;

  let root = null;
  let payload = null;
  let searchIndex = [];
  let searchIndexTokenized = [];
  let ressourceTree = null;
  let statsByCategory = {};
  let statsByCategoryPath = {};
  let categoryNodes = [];


  function escapeHTML(value) {
    return (value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function $(selector, scope) {
    return (scope || root || document).querySelector(selector);
  }

  function $$(selector, scope) {
    return Array.from((scope || root || document).querySelectorAll(selector));
  }

  function normalizeText(value) {
    return (value || "")
      .toString()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");
  }

  function formatDate(value) {
    if (!value) return null;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;

    return date.toLocaleDateString("fr-FR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  }

  const MAX_LATEST_DOCUMENTS = 50;

  function getFirstSeenDate(item) {
    return (
      item.first_seen_at ||
      item.created_at ||
      item.modified_at ||
      null
    );
}

  function renderLatestDocuments() {
    const toggle = $("#ressourceLatestToggle");
    const panel = $("#ressourceLatestPanel");
    const list = $("#ressourceLatestList");
    const count = $("#ressourceLatestCount");

    if (!toggle || !panel || !list) return;

    const latest = searchIndex
      .filter((item) => getFirstSeenDate(item))
      .sort((a, b) => {
        return new Date(getFirstSeenDate(b)) - new Date(getFirstSeenDate(a));
      })
      .slice(0, MAX_LATEST_DOCUMENTS);

    if (!latest.length) {
      toggle.style.display = "none";
      return;
    }

    if (count) {
      count.textContent = `(${latest.length})`;
    }

    list.innerHTML = "";

    let currentDate = "";

    latest.forEach((item) => {
      const dateLabel = formatDate(getFirstSeenDate(item)) || "Date inconnue";

      if (dateLabel !== currentDate) {
        currentDate = dateLabel;

        const groupTitle = document.createElement("div");
        groupTitle.className = "ressource-latest-date";
        groupTitle.textContent = dateLabel;
        list.appendChild(groupTitle);
      }

      const link = document.createElement("a");
      link.className = "ressource-latest-card";

      const url = item.share_url || item.category_url || "#";
      const opensParentFolder = !item.share_url && !!item.category_url;
      const isLocked = !!item.locked;
      const requiredLabel = item.required_visibility_label || "Compte public";

      link.className = "list-group-item list-group-item-action search-result-card";

      if (isLocked) {
        link.classList.add("disabled");
        link.title = "Accès restreint : " + requiredLabel;

        link.addEventListener("click", (event) => {
          event.preventDefault();
        });

      } else {
        // ✅ Élément accessible
        link.href = url;

        if (url && url !== "#" && !url.startsWith("/")) {
          link.target = "_blank";
          link.rel = "noopener noreferrer";
        }
      }

      const title = document.createElement("strong");
      title.textContent = item.name || "Document sans nom";

      const meta = document.createElement("span");
      meta.className = "ressource-latest-meta";

      const details = [];

      if (item.category) {
        details.push(cleanCategoryTitle(item.category));
      }

      if (item.extension) {
        details.push(item.extension.replace(".", "").toUpperCase());
      }

      if (item.size_human) {
        details.push(item.size_human);
      }

      meta.textContent = details.join(" · ");

      link.appendChild(title);
      link.appendChild(meta);

      list.appendChild(link);
    });

    toggle.addEventListener("click", () => {
      const isOpen = !panel.classList.contains("d-none");

      panel.classList.toggle("d-none", isOpen);
      toggle.classList.toggle("is-open", !isOpen);
      toggle.setAttribute("aria-expanded", String(!isOpen));
    });
  }


  function cleanCategoryTitle(name) {
    return (name || "").replace(/^\d+\s*-\s*/, "").trim();
  }

  function getCategoryIcon(name) {
    const lower = normalizeText(name);

    if (lower.includes("rapport")) return "📊";
    if (lower.includes("publication")) return "🎓";
    if (lower.includes("fiche")) return "🛠";
    if (lower.includes("communication")) return "📣";
    if (lower.includes("collectiv")) return "🏛";
    if (lower.includes("alimentation") || lower.includes("agriculture")) return "🌱";
    if (lower.includes("partenaire") || lower.includes("convention")) return "🤝";
    if (lower.includes("numerique")) return "💻";
    if (lower.includes("juridique") || lower.includes("reglementaire")) return "⚖️";
    if (lower.includes("autres")) return "📚";

    return "📁";
  }

  function getCategoryDescription(name) {
    const descriptions = {
      "1 - Rapports Institutionnels":
        "Rapports institutionnels, études publiques et documents de référence utiles pour situer les monnaies locales dans leur environnement politique, économique et territorial.",
      "2 - Publications académiques":
        "Thèses, mémoires, articles et travaux universitaires consacrés aux monnaies locales, à l’économie territoriale et aux communs monétaires.",
      "3 - Fiches pratiques pour les MLC":
        "Fiches, modèles, exemples et outils opérationnels pour aider les associations de monnaies locales dans leur fonctionnement quotidien.",
      "4 - Communication":
        "Ressources visuelles, supports de communication, logos, expositions, revues de presse et éléments graphiques.",
      "5 - Collectivités Territoriales & MLC":
        "Guides, conventions, kits et exemples de coopérations entre monnaies locales et collectivités territoriales.",
      "6 - Alimentation et agriculture durable":
        "Ressources sur les liens entre monnaies locales, alimentation durable, agriculture, démocratie alimentaire et sécurité sociale de l’alimentation.",
      "7 - Partenaires et Conventions":
        "Conventions, documents partenariaux et ressources liées aux relations nationales ou locales avec des structures alliées.",
      "8 - Outils Numériques":
        "Documents relatifs aux outils numériques, aux plateformes, à la cartographie et aux usages digitaux des monnaies locales.",
      "9 - Autres documents externes":
        "Documents complémentaires, guides associatifs et ressources utiles pour élargir les réflexions du réseau.",
      "10 - documents juridiques et réglementaires":
        "Textes, analyses juridiques, notes réglementaires et ressources liées au cadre bancaire, fiscal ou institutionnel des monnaies locales.",
    };

    return descriptions[name] || "Ressources disponibles dans cette thématique.";
  }

  function getNodeFileCount(node, depth = 0) {
    const MAX_DEPTH = 50;

    if (!node || depth > MAX_DEPTH) return 0;

    const children = node.children || [];
    let count = 0;

    for (const child of children) {
      if (child.type === "file") {
        count += 1;
      } else if (child.type === "directory") {
        count += getNodeFileCount(child, depth + 1);
      }
    }

    return count;
  }

  async function loadData() {
    const info = $("#ressourceSearchInfo");
    const hasPrivateSearch = !!$("#ressourceSearchInput");

    const privateUrl = root.dataset.privateJsonUrl;
    const publicUrl = root.dataset.publicTreeUrl;
    const url = hasPrivateSearch ? privateUrl : publicUrl;

    if (!url) {
      throw new Error("URL JSON manquante sur #ressource-center-page");
    }

    if (info) info.textContent = "Chargement de l’index…";

    const response = await fetch(url, { cache: "no-store" });

    if (!response.ok) {
      throw new Error(`Impossible de charger le JSON : ${response.status}`);
    }

    payload = await response.json();

    searchIndex = payload.search_index || [];
    searchIndexTokenized = searchIndex.map((item) => {
      const fields = getItemSearchFields(item);

      return {
        item,
        fields,
        fieldTokens: {
          name: tokenize(fields.name),
          parent: tokenize(fields.parent),
          relativePath: tokenize(fields.relativePath),
          category: tokenize(fields.category),
          extension: tokenize(fields.extension),
          mime: tokenize(fields.mime),
          full: tokenize(fields.full),
        },
      };
    });

    ressourceTree = payload.tree || null;
    statsByCategory = payload.stats?.by_category || {};
    statsByCategoryPath = payload.stats?.by_category_path || {};

    if (info) {
      info.textContent = "Index chargé. Tape un mot-clé pour rechercher.";
    }
  }


  function getNodePath(node) {
    return node?.relative_path || node?.name || "";
  }

  function findNodeByPath(path, currentNode = ressourceTree) {
    if (!currentNode) return null;

    const currentPath = getNodePath(currentNode);

    if (currentPath === path) {
      return currentNode;
    }

    for (const child of currentNode.children || []) {
      if (child.type !== "directory") continue;

      const found = findNodeByPath(path, child);
      if (found) return found;
    }

    return null;
  }

  function getNodeAncestors(node) {
    const path = getNodePath(node);
    if (!path) return [];

    const parts = path.split("/").filter(Boolean);
    const ancestors = [];

    let currentPath = "";

    parts.forEach((part) => {
      currentPath = currentPath ? `${currentPath}/${part}` : part;

      const ancestorNode = findNodeByPath(currentPath);

      ancestors.push({
        label: cleanCategoryTitle(part),
        path: currentPath,
        node: ancestorNode,
      });
    });

    return ancestors;
  }

  function getDirectChildFolders(node) {
    return (node?.children || [])
      .filter((child) => child.type === "directory")
      .sort((a, b) =>
        (a.name || "").localeCompare(b.name || "", "fr", {
          numeric: true,
          sensitivity: "base",
        })
      );
  }

  function getDirectFiles(node) {
    return (node?.children || [])
      .filter((child) => child.type === "file")
      .sort((a, b) =>
        (a.name || "").localeCompare(b.name || "", "fr", {
          numeric: true,
          sensitivity: "base",
        })
      );
  }

  function getTopCategoryNode(node) {
    const path = node?.relative_path || "";

    if (!path) return node;

    const topLevelPath = path.split("/").filter(Boolean)[0];

    return categoryNodes.find((category) => {
      return category.relative_path === topLevelPath || category.name === topLevelPath;
    }) || node;
  }

    function selectExplorerNode(node) {
      if (!node) return;

      const topCategory = getTopCategoryNode(node);

      updateCategoryPanel(topCategory, node);
      renderCentralExplorer(node);
    }
  
  function renderCentralExplorer(node) {
    renderBreadcrumb(node);
    renderChildFolders(node);
    renderDirectFiles(node);
  }

  function renderBreadcrumb(node) {
    const container = $("#ressourceBreadcrumb");
    if (!container) return;

    container.innerHTML = "";

    const ancestors = getNodeAncestors(node);

    if (!ancestors.length) return;

    const wrapper = document.createElement("div");
    wrapper.className = "d-flex flex-wrap align-items-center gap-1 small text-muted";

    const rootButton = document.createElement("button");
    rootButton.type = "button";
    rootButton.className = "btn btn-sm btn-link p-0 text-decoration-none";
    rootButton.textContent = "Centre de ressources";
    rootButton.addEventListener("click", () => {
      if (ressourceTree) selectExplorerNode(ressourceTree);
    });

    wrapper.appendChild(rootButton);

    ancestors.forEach((ancestor) => {
      const separator = document.createElement("span");
      separator.textContent = "›";
      separator.className = "mx-1";
      wrapper.appendChild(separator);

      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-sm btn-link p-0 text-decoration-none";
      button.textContent = ancestor.label;

      if (ancestor.node) {
        button.addEventListener("click", () => selectExplorerNode(ancestor.node));
      } else {
        button.disabled = true;
      }

      wrapper.appendChild(button);
    });

    container.appendChild(wrapper);
  }

  function renderChildFolders(node) {
    const container = $("#ressourceChildFolders");
    if (!container) return;

    container.innerHTML = "";

    const folders = getDirectChildFolders(node);

    if (!folders.length) return;

    const title = document.createElement("div");
    title.className = "small text-uppercase text-muted mb-2";
    title.style.textAlign = "left";
    title.textContent = "Sous-dossiers";

    const grid = document.createElement("div");
    grid.className = "ressource-folder-grid";

    folders.forEach((folder) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ressource-folder-card";
      button.addEventListener("click", () => selectExplorerNode(folder));

      const folderTitle = document.createElement("strong");
      folderTitle.textContent = `📁 ${cleanCategoryTitle(folder.name || "")}`;

      const count = document.createElement("small");
      count.textContent = `${getNodeFileCount(folder)} document(s)`;

      button.appendChild(folderTitle);
      button.appendChild(count);

      grid.appendChild(button);
    });

    container.appendChild(title);
    container.appendChild(grid);
  }

  function renderDirectFiles(node) {
    const container = $("#ressourceDirectFiles");
    if (!container) return;

    container.innerHTML = "";

    const files = getDirectFiles(node);
    if (!files.length) return;

    const title = document.createElement("div");
    title.className = "small text-uppercase text-muted mb-2";
    title.style.textAlign = "left";
    title.textContent = "Documents";

    const list = document.createElement("div");
    list.className = "list-group ressource-files-scroll";

    files.forEach((file) => {
      const link = document.createElement("a");
      const url = file.share_url || file.category_url || "#";

      link.className = "list-group-item list-group-item-action";
      link.href = url;

      if (url && url !== "#") {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }

      link.innerHTML = `
        <strong>📄 ${escapeHTML(file.name || "Document")}</strong><br>
        <small class="text-muted">
          ${escapeHTML(file.extension || "")}
          ${file.size_human ? " · " + escapeHTML(file.size_human) : ""}
        </small>
      `;

      list.appendChild(link);
    });

    container.appendChild(title);
    container.appendChild(list);
  }

  function renderCategoryNav() {
    console.log("🔥 renderCategoryNav lancé", categoryNodes.length);
    const nav = $("#ressourceCategoryNav");
    if (!nav || !ressourceTree) return;

    nav.innerHTML = "";

    categoryNodes = (ressourceTree.children || [])
      .filter((child) => child.type === "directory")
      .sort((a, b) =>
        (a.name || "").localeCompare(b.name || "", "fr", {
          numeric: true,
          sensitivity: "base",
        })
      );

    categoryNodes.forEach((category, index) => {
      const button = document.createElement("button");

      button.type = "button";
      button.className = "list-group-item list-group-item-action";
      if (index === 0) button.classList.add("active");

      button.dataset.categoryKey = category.relative_path || category.name;
      button.textContent = `${getCategoryIcon(category.name)} ${cleanCategoryTitle(category.name)}`;

      button.addEventListener("click", () => {
        console.log("🔥 clic catégorie direct", category.name);
        selectExplorerNode(category);
      });

      nav.appendChild(button);
    });

    if (categoryNodes[0]) {
      selectExplorerNode(categoryNodes[0]);
    }
  }

  function initCategoryNavClicks() {
    const nav = $("#ressourceCategoryNav");
    if (!nav) return;

    console.log("🔥 initCategoryNavClicks lancé", nav);
    nav.addEventListener("click", (event) => {
      console.log("🔥 clic délégué nav", event.target);
      const button = event.target.closest("button[data-category-key]");
      if (!button) return;

      const key = button.dataset.categoryKey;

      const category = categoryNodes.find((node) => {
        return (node.relative_path || node.name) === key;
      });

      if (category) {
        selectExplorerNode(category);
      }
    });
  }

  function updateCategoryPanel(category, currentNode = category) {
    const title = $("#ressourceCategoryTitle");
    const description = $("#ressourceCategoryDescription");
    const stats = $("#ressourceCategoryStats");
    const link = $("#ressourceCategoryLink");
    const nav = $("#ressourceCategoryNav");

    if (!category || category === ressourceTree) {
      if (title) title.textContent = "📁 Centre de ressources";
      if (description) description.textContent = "Vue globale de toutes les ressources disponibles.";
      if (stats) stats.textContent = "";

      if (link) {
        link.textContent = "";
        link.style.display = "none";
        link.onclick = null;
        link.removeAttribute("href");
        link.removeAttribute("target");
        link.removeAttribute("rel");
      }

      return;
    }

    if (nav) {
      $$(".list-group-item", nav).forEach((button) => {
        button.classList.toggle(
          "active",
          button.dataset.categoryKey === (category.relative_path || category.name)
        );
      });
    }

    const categoryName = category.name || "";
    const categoryRelativePath = category.relative_path || categoryName;

    const count =
      statsByCategoryPath[categoryRelativePath] ||
      statsByCategory[categoryName] ||
      getNodeFileCount(category);

    if (title) {
      title.textContent = `${getCategoryIcon(categoryName)} ${cleanCategoryTitle(categoryName)}`;
    }

    if (description) {
      description.textContent = getCategoryDescription(categoryName);
    }

    if (stats) {
      stats.textContent = count
        ? `${count} document(s) disponible(s) dans cette catégorie.`
        : "";
    }

    if (link) {
      const parentPath = currentNode?.parent_relative_path || "";
      const parentNode = parentPath ? findNodeByPath(parentPath) : ressourceTree;
      link.removeAttribute("href");
      link.removeAttribute("target");
      link.removeAttribute("rel");

      link.classList.remove("btn-primary", "btn-outline-primary");
      link.classList.add("btn-outline-primary");

      if (parentNode) {
        link.textContent = "← Retour";
        link.style.display = "";
        link.onclick = (event) => {
          event.preventDefault();
          selectExplorerNode(parentNode);
        };
      } else {
        link.textContent = "";
        link.style.display = "none";
        link.onclick = null;
      }
    }
  }

  function stripPlural(token) {
  if (!token || token.length <= 5) return token;

  // cas spécifiques français
  if (token.endsWith("eaux")) return token.slice(0, -1);
  if (token.endsWith("aux")) return token.slice(0, -3) + "al";

  // suppression du "s" seulement si mot assez long
  if (token.length > 5 && token.endsWith("s")) {
    return token.slice(0, -1);
  }

  return token;
}

function tokenize(value) {
  return normalizeText(value)
    .replace(/[-_./|()'’"]/g, " ")
    .split(/\s+/)
    .map(stripPlural)
    .filter((token) => token.length >= 2);
}

function uniqueTokens(tokens) {
  return Array.from(new Set(tokens));
}

function getItemSearchFields(item) {
  return {
    name: normalizeText(item.name || ""),
    parent: normalizeText(item.parent_relative_path || ""),
    relativePath: normalizeText(item.relative_path || ""),
    category: normalizeText(item.category || ""),
    extension: normalizeText(item.extension || ""),
    mime: normalizeText(item.mime_type || ""),
    full: normalizeText(item.search_text || ""),
  };
}

function scoreTokenAgainstField(token, fieldValue, fieldTokens, weight) {
  if (!token || !fieldValue) return 0;

  if ((fieldTokens || []).includes(token)) {
    return weight;
  }

  if ((fieldTokens || []).some((fieldToken) => fieldToken.startsWith(token) || token.startsWith(fieldToken))) {
    return weight * 0.72;
  }

  if (fieldValue.includes(token)) {
    return weight * 0.45;
  }

  return 0;
}

function scoreressourceItem(indexedItem, queryTokens, rawQuery) {
  const { fields, fieldTokens } = indexedItem;

  let score = 0;
  let matchedTokens = 0;

  queryTokens.forEach((token) => {
    const tokenScore =
      scoreTokenAgainstField(token, fields.name, fieldTokens.name, 12) +
      scoreTokenAgainstField(token, fields.parent, fieldTokens.parent, 7) +
      scoreTokenAgainstField(token, fields.category, fieldTokens.category, 6) +
      scoreTokenAgainstField(token, fields.relativePath, fieldTokens.relativePath, 4) +
      scoreTokenAgainstField(token, fields.full, fieldTokens.full, 2) +
      scoreTokenAgainstField(token, fields.extension, fieldTokens.extension, 1) +
      scoreTokenAgainstField(token, fields.mime, fieldTokens.mime, 1);

    if (tokenScore > 0) {
      matchedTokens += 1;
      score += tokenScore;
    }
  });

  if (matchedTokens === queryTokens.length) {
    score += 20;
  }

  if (rawQuery && rawQuery.length >= 4) {
    if (fields.name.includes(rawQuery)) score += 30;
    if (fields.parent.includes(rawQuery)) score += 16;
    if (fields.relativePath.includes(rawQuery)) score += 10;
    if (fields.full.includes(rawQuery)) score += 6;
  }

  const nameLength = fields.name.length || 1;
  if (score > 0 && nameLength < 80) {
    score += 4;
  }

  return { score, matchedTokens };
}

  function searchressources(query) {
    const rawQuery = normalizeText(query);
    const queryTokens = uniqueTokens(tokenize(query));

    if (!rawQuery || !queryTokens.length) {
      return {
        total: 0,
        results: [],
      };
    }

    const scoredResults = searchIndexTokenized
      .map((indexedItem) => {
        const scoring = scoreressourceItem(indexedItem, queryTokens, rawQuery);

        return {
          item: indexedItem.item,
          score: scoring.score,
          matchedTokens: scoring.matchedTokens,
        };
      })
          
      .filter((result) => result.score > 0)
      .sort((a, b) => {
        // Score principal
        if (b.score !== a.score) return b.score - a.score;

        // Puis nombre de mots couverts
        if (b.matchedTokens !== a.matchedTokens) {
          return b.matchedTokens - a.matchedTokens;
        }

        // Puis titre plus court = souvent plus pertinent
        const aNameLength = (a.item.name || "").length;
        const bNameLength = (b.item.name || "").length;
        return aNameLength - bNameLength;
      });

    return {
      total: scoredResults.length,
      results: scoredResults.slice(0, MAX_RESULTS).map((result) => result.item),
    };
  }


  function renderSearchResults(results, total, query) {
    const container = $("#ressourceSearchResults");
    const wrapper = $("#ressourceSearchResultsWrapper");
    const info = $("#ressourceSearchInfo");

    if (!container) return;

    container.innerHTML = "";

    if (!query.trim()) {
      if (wrapper) wrapper.style.display = "none";
      if (info) info.textContent = "Tape un mot-clé pour rechercher.";
      return;
    }

    if (!results.length) {
      if (wrapper) wrapper.style.display = "none";
      if (info) info.textContent = "Aucun résultat.";
      return;
    }

    if (wrapper) wrapper.style.display = "block";

    if (info) {
      info.textContent =
        total > results.length
          ? `${total} résultat(s) — affichage des ${results.length} premiers.`
          : `${total} résultat(s).`;
    }

    results.forEach((item) => {
      const link = document.createElement("a");

      const url = item.share_url || item.category_url || "#";
      const opensParentFolder = !item.share_url && !!item.category_url;
      const isLocked = !!item.locked;
      const requiredLabel = item.required_visibility_label || "Compte public";

      link.className =
        "ressource-latest-card list-group-item list-group-item-action search-result-card";

      if (isLocked) {
        const badge = document.createElement("span");
        badge.textContent = " 🔒";
        badge.style.marginLeft = "6px";
        link.appendChild(badge);
        
        link.href = "#";

        link.classList.add("disabled");
        link.title = "Accès restreint : " + requiredLabel;

        link.addEventListener("click", (event) => {
          event.preventDefault();
        });

      } else {
        link.href = url;
        link.title = opensParentFolder
          ? "Lien direct indisponible : ouvre le dossier parent"
          : "Ouvrir le fichier";

        if (url && url !== "#" && !url.startsWith("/")) {
          link.target = "_blank";
          link.rel = "noopener noreferrer";
        }
      }

      const title = document.createElement("div");
      title.className = "fw-semibold mb-1";
      title.textContent = item.name || "Fichier sans nom";

      const path = document.createElement("div");
      path.className = "small text-muted mb-2 search-result-path";
      path.textContent =
        item.parent_relative_path ||
        item.relative_path ||
        item.category ||
        "";

      const metadata = [];

      if (item.extension) {
        metadata.push(item.extension.replace(".", "").toUpperCase());
      }

      if (item.page_count !== null && item.page_count !== undefined) {
        metadata.push(`${item.page_count} page${item.page_count > 1 ? "s" : ""}`);
      }

      if (item.size_human) {
        metadata.push(item.size_human);
      }

      const modifiedAt = formatDate(item.modified_at);
      if (modifiedAt) {
        metadata.push(`modifié le ${modifiedAt}`);
      }

      const meta = document.createElement("div");
      meta.className = "small text-muted";
      meta.textContent = metadata.join(" · ");

      link.appendChild(title);
      link.appendChild(path);
      link.appendChild(meta);

      container.appendChild(link);
    });
  }
    function debounce(fn, delay) {
      let timer;
      return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
      };
    }

  function initSearch() {
    const input = $("#ressourceSearchInput");
    const button = $("#ressourceSearchButton");

    if (!input || !button) return;

    const runSearch = () => {
      const query = input.value || "";
      const search = searchressources(query);
      renderSearchResults(search.results, search.total, query);
    };

    const debouncedSearch = debounce(runSearch, 150);

    input.addEventListener("input", debouncedSearch);
    button.addEventListener("click", runSearch);

    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        runSearch(); // direct → pas de délai
      }
    });
  }

  function initSearchCloseBehavior() {
    const wrapper = $("#ressourceSearchResultsWrapper");
    const input = $("#ressourceSearchInput");

    if (!wrapper || !input) return;

    document.addEventListener("click", (event) => {
      if (!root.contains(event.target)) return;
      if (wrapper.contains(event.target)) return;
      if (input.contains(event.target)) return;

      wrapper.style.display = "none";
    });
  }

  function buildTreeHTML(node, level = 0) {
    if (!node) return "";

    const children = node.children || [];

    const directories = children
      .filter((child) => child.type === "directory")
      .sort((a, b) =>
        (a.name || "").localeCompare(b.name || "", "fr", {
          numeric: true,
          sensitivity: "base",
        })
      );

    const files = children.filter((child) => child.type === "file");
    const count = files.length || node.file_count || 0;
    const hasChildren = directories.length > 0 || count > 0;

    const classes = [
      "tree-label",
      level === 1 ? "tree-main-category" : "",
      hasChildren ? "tree-collapsible" : "",
    ]
      .filter(Boolean)
      .join(" ");

    const isOpenByDefault = level === 0;
    const chevron = hasChildren ? (isOpenByDefault ? "▾" : "▸") : "";
    const name = node.name || "Centre de ressources";
    const safeName = escapeHTML(name);
    const safeRelativePath = escapeHTML(node.relative_path || "");

    const isLocked = !!node.locked;
    const lockIcon = isLocked ? ` <span class="tree-lock-icon" title="Accès restreint">🔒</span>` : "";

    let html = `
      <li class="tree-level-${level}">
        <span class="${classes}"
              data-node-name="${safeName}"
              data-relative-path="${safeRelativePath}"
              data-open="${isOpenByDefault ? "true" : "false"}"
              ${hasChildren ? 'data-collapsible="true"' : ""}>
          ${hasChildren ? `<span class="tree-chevron">${chevron}</span>` : ""}
          <span class="tree-node-name">${safeName}${lockIcon}</span>
        </span>
    `;

    if (hasChildren) {
      html += level === 0 ? `<ul style="display:block;">` : `<ul style="display:none;">`;

      directories.forEach((directory) => {
        html += buildTreeHTML(directory, level + 1);
      });

      if (count > 0) {
        const requiredLabel = node.required_visibility_label || "Compte public";
        const fileLabel = `📄 ${count} fichier${count > 1 ? "s" : ""}`;

        if (isLocked) {
          html += `
            <li class="tree-files">
              <span class="tree-file-count tree-file-count-locked"
                    title="Section réservée : ${requiredLabel.replace(/"/g, "&quot;")}">
                🔒 ${fileLabel} · réservé à ${requiredLabel}
              </span>
            </li>
          `;
        } else {
          html += `
            <li class="tree-files">
              <span class="tree-file-count">
                ${fileLabel}
              </span>
            </li>
          `;
        }
      }

      html += "</ul>";
    }

    html += "</li>";
    return html;
  }

  function initPreviewCollapse() {
    const collapse = document.getElementById("ressourcePreviewCollapse");
    const treeContainer = document.getElementById("ressourcePreviewTree");

    if (!collapse || !treeContainer) return;

    collapse.addEventListener("shown.bs.collapse", () => {
      // Force le rendu de l’arborescence quand on ouvre
      renderTree("#ressourcePreviewTree");
    });
  }

  function renderTree(selector) {
    const container = $(selector);
    if (!container || !ressourceTree) return;

    container.innerHTML = `<ul class="tree-root">${buildTreeHTML(ressourceTree)}</ul>`;

    $$(".tree-collapsible", container).forEach((label) => {
      label.addEventListener("click", function () {
        const li = this.parentElement;
        const ul = li.querySelector(":scope > ul");

        if (!ul) return;

        const isOpen = this.dataset.open === "true";
        const nextOpen = !isOpen;

        ul.style.display = nextOpen ? "block" : "none";
        this.dataset.open = String(nextOpen);

        const chevron = this.querySelector(".tree-chevron");
        if (chevron) {
          chevron.textContent = nextOpen ? "▾" : "▸";
        }

        if (this.classList.contains("tree-main-category")) {
          const relativePath = this.dataset.relativePath;
          const category = categoryNodes.find((node) => {
            return (node.relative_path || node.name) === relativePath || node.name === this.dataset.nodeName;
          });

          if (category) {
            selectExplorerNode(category);
          }
        }
      });
    });
  }

  function initExplorerToggle() {
    const toggle = $("#ressourceViewToggle");
    const categoriesView = $("#ressourceCategoriesView");
    const treeView = $("#ressourceTreeView");

    if (!toggle || !categoriesView || !treeView) return;

    const update = () => {
      const treeMode = toggle.checked;
      categoriesView.classList.toggle("d-none", treeMode);
      treeView.classList.toggle("d-none", !treeMode);
    };

    toggle.addEventListener("change", update);
    update();
  }

  async function init() {
    console.log("🔥 init centre ressources lancé");
    root = document.querySelector(RESSOURCE_ROOT_SELECTOR);

    if (!root) return;

    try {
      await loadData();

      renderCategoryNav();
      initCategoryNavClicks();
      renderTree("#ressourceArchitectureContent");
      renderTree("#ressourcePreviewTree");
      renderLatestDocuments();

      initSearch();
      initSearchCloseBehavior();
      initExplorerToggle();
      initPreviewCollapse();

      console.info(
        "[Centre ressources] chargé",
        searchIndex.length,
        "fichiers,",
        categoryNodes.length,
        "catégories"
      );
    } catch (error) {
      console.error("[Centre ressources] erreur :", error);

      const info = $("#ressourceSearchInfo");
      if (info) {
        info.textContent = "Impossible de charger le centre de ressources.";
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
