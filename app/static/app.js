(function () {
  "use strict";

  var form = document.getElementById("search-form");
  var siteInput = document.getElementById("site");
  var wantedInput = document.getElementById("wanted");
  var button = document.getElementById("go");
  var statusBox = document.getElementById("status");
  var statusText = document.getElementById("status-text");
  var bar = document.getElementById("bar");
  var errorBox = document.getElementById("error");
  var results = document.getElementById("results");

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function isWebAddress(url) {
    return typeof url === "string" && /^https?:\/\//i.test(url);
  }

  function showError(message) {
    statusBox.hidden = true;
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  function clearOutput() {
    errorBox.hidden = true;
    errorBox.textContent = "";
    results.textContent = "";
    bar.hidden = true;
    bar.value = 0;
  }

  function resultCard(item, label, isBest) {
    var card = el("article", "card" + (isBest ? " best" : ""));
    if (label) card.appendChild(el("p", "label " + (item.strength || ""), label));
    var heading = el("h2");
    if (isWebAddress(item.url)) {
      var link = el("a", "", item.title || item.url);
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      heading.appendChild(link);
    } else {
      heading.textContent = item.title || "Result";
    }
    card.appendChild(heading);
    var kind = item.kind === "pdf" ? "PDF file · " : item.kind === "document" ? "Document · " : "";
    card.appendChild(el("p", "url", kind + item.url));
    if (item.reasons && item.reasons.length) {
      var list = el("ul", "reasons");
      item.reasons.forEach(function (reason) {
        list.appendChild(el("li", "", reason));
      });
      card.appendChild(list);
    }
    if (item.missing && item.missing.length) {
      card.appendChild(el("p", "missing", "Not found on this page: " + item.missing.join(", ")));
    }
    return card;
  }

  function showResults(data) {
    statusBox.hidden = true;
    results.textContent = "";
    if (!data.best) {
      results.appendChild(el("p", "empty", data.message || "I did not find a page that matches that request."));
    } else {
      results.appendChild(resultCard(data.best, data.message, true));
      if (data.others && data.others.length) {
        results.appendChild(el("h3", "others-title", "Other pages that might help"));
        data.others.forEach(function (item) {
          results.appendChild(resultCard(item, "", false));
        });
      }
    }
    var notes = (data.notes || []).slice();
    notes.push("Pages read: " + data.pages_checked + ".");
    var list = el("ul", "notes");
    notes.forEach(function (note) {
      list.appendChild(el("li", "", note));
    });
    results.appendChild(list);
  }

  function handle(event) {
    if (event.type === "status") {
      statusText.textContent = event.message;
    } else if (event.type === "progress") {
      statusText.textContent = "Read " + event.pages + " page" + (event.pages === 1 ? "" : "s") + "...";
      bar.hidden = false;
      bar.max = event.limit;
      bar.value = event.pages;
    } else if (event.type === "results") {
      showResults(event);
    } else if (event.type === "error") {
      showError(event.message);
    }
  }

  async function search(site, wanted) {
    var response;
    try {
      response = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: site, request: wanted }),
      });
    } catch (err) {
      showError("I could not reach the server. Check your connection and try again.");
      return;
    }
    if (!response.ok) {
      var message = "Something went wrong. Please try again.";
      try {
        var body = await response.json();
        if (body && body.error) message = body.error;
      } catch (err) { /* keep the default message */ }
      showError(message);
      return;
    }
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    for (;;) {
      var chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      var newline;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        var line = buffer.slice(0, newline).trim();
        buffer = buffer.slice(newline + 1);
        if (line) {
          try { handle(JSON.parse(line)); } catch (err) { /* ignore a broken line */ }
        }
      }
    }
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    var site = siteInput.value.trim();
    var wanted = wantedInput.value.trim();
    clearOutput();
    if (!site || !wanted) {
      showError("Fill in both boxes: the website address and what you want to find.");
      return;
    }
    button.disabled = true;
    statusText.textContent = "Starting...";
    statusBox.hidden = false;
    try {
      await search(site, wanted);
    } finally {
      button.disabled = false;
      if (!results.firstChild && errorBox.hidden) statusBox.hidden = true;
    }
  });
})();
