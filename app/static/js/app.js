/* ============================================================
   Invoice Extractor - frontend
   The visual design is intentionally unchanged: the same CSS
   classes and markup structure are used for rendered results.
============================================================ */

const dropArea = document.getElementById("dropArea");
const fileInput = document.getElementById("invoice");
const fileName = document.getElementById("fileName");
const resultsContainer = document.getElementById("resultsContainer");
const loading = document.getElementById("loading");
const loadingStatus = document.getElementById("loadingStatus");

const POLL_INTERVAL_MS = 1500;
const POLL_TIMEOUT_MS = 10 * 60 * 1000;

const CURRENCY_SYMBOLS = {
    INR: "₹",
    USD: "$",
    EUR: "€",
    GBP: "£",
    JPY: "¥"
};

/* ============================
   Small helpers
============================ */

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) {
        node.className = className;
    }
    if (text !== undefined && text !== null) {
        node.textContent = text;
    }
    return node;
}

function sleep(ms) {
    return new Promise(function (resolve) {
        setTimeout(resolve, ms);
    });
}

function isPdfFile(file) {
    return !!file && /\.pdf$/i.test(file.name || "");
}

function display(value) {
    if (value === null || value === undefined || value === "") {
        return "Not Available";
    }
    return String(value);
}

function money(value, currency) {
    if (value === null || value === undefined || value === "") {
        return "Not Available";
    }
    const number = Number(value);
    if (!Number.isFinite(number)) {
        return String(value);
    }
    const code = (currency || "").toUpperCase();
    const symbol = CURRENCY_SYMBOLS[code];
    const formatted = number.toLocaleString("en-IN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
    if (symbol) {
        return symbol + " " + formatted;
    }
    return (code ? code + " " : "") + formatted;
}

function seconds(value) {
    if (value === null || value === undefined || value === "") {
        return null;
    }
    return Number(value).toFixed(2) + " sec";
}

/* ============================
   Drag & Drop
============================ */

dropArea.addEventListener("dragover", function (e) {
    e.preventDefault();
    dropArea.classList.add("dragover");
});

dropArea.addEventListener("dragleave", function () {
    dropArea.classList.remove("dragover");
});

dropArea.addEventListener("drop", function (e) {
    e.preventDefault();
    dropArea.classList.remove("dragover");

    const dropped = Array.from(e.dataTransfer.files || []);
    const pdfs = dropped.filter(isPdfFile);

    if (pdfs.length !== dropped.length) {
        alert("Only PDF files are supported.");
    }

    const transfer = new DataTransfer();
    pdfs.forEach(function (file) {
        transfer.items.add(file);
    });
    fileInput.files = transfer.files;
    showFileName(fileInput);
});

/* ============================
   Click Upload Card
============================ */

dropArea.addEventListener("click", function (e) {
    // The label already opens the picker; avoid opening it twice.
    if (e.target.closest("label") || e.target === fileInput) {
        return;
    }
    fileInput.click();
});

/* ============================
   Show Selected Files
============================ */

function showFileName(input) {
    const files = Array.from(input.files || []);

    if (files.length === 0) {
        fileName.textContent = "No files selected";
        return;
    }

    fileName.textContent = "";

    const heading = el("strong", null, "Selected Files");
    fileName.appendChild(heading);
    fileName.appendChild(document.createElement("br"));
    fileName.appendChild(document.createElement("br"));

    files.forEach(function (file) {
        fileName.appendChild(document.createTextNode("✅ " + file.name));
        fileName.appendChild(document.createElement("br"));
    });
}

/* ============================
   Prevent Browser Opening PDF
============================ */

["dragenter", "dragover", "dragleave", "drop"].forEach(function (eventName) {
    document.body.addEventListener(eventName, function (e) {
        e.preventDefault();
        e.stopPropagation();
    });
});

/* ============================
   Accordion
============================ */

function toggleInvoice(id, button) {
    const allBodies = document.querySelectorAll(".invoice-body");
    const allButtons = document.querySelectorAll(".view-btn");

    allBodies.forEach(function (body) {
        if (body.id !== id) {
            body.style.display = "none";
        }
    });

    allButtons.forEach(function (btn) {
        if (btn !== button) {
            btn.innerHTML = "View Extracted Info";
        }
    });

    const current = document.getElementById(id);

    if (!current) {
        return;
    }

    if (current.style.display === "block") {
        current.style.display = "none";
        button.innerHTML = "View Extracted Info";
    } else {
        current.style.display = "block";
        button.innerHTML = "Hide Info";
    }
}

/* ============================
   Loading / errors
============================ */

function setButtonsDisabled(disabled) {
    document.querySelectorAll(".extract-btn").forEach(function (btn) {
        btn.disabled = disabled;
    });
}

function showLoading(message) {
    loadingStatus.textContent = message || "Please wait...";
    loading.style.display = "block";
    setButtonsDisabled(true);
}

function hideLoading() {
    loading.style.display = "none";
    setButtonsDisabled(false);
}

function clearResults() {
    resultsContainer.textContent = "";
}

function showError(message) {
    clearResults();
    resultsContainer.appendChild(el("div", "error", "❌ " + message));
}

async function readJson(response) {
    try {
        return await response.json();
    } catch (error) {
        return {};
    }
}

function responseError(data, response) {
    if (typeof data.error === "string" && data.error) {
        return data.error;
    }
    if (typeof data.detail === "string" && data.detail) {
        return data.detail;
    }
    if (Array.isArray(data.details) && data.details.length > 0) {
        return data.details[0].msg || "Invalid request.";
    }
    return "Request failed (HTTP " + response.status + ").";
}

/* ============================
   Submit Buttons
============================ */

function submitApproach1() {
    uploadInvoices("/upload");
}

function submitApproach2() {
    uploadInvoices("/upload-approach2");
}

async function uploadInvoices(url) {
    const files = Array.from(fileInput.files || []);

    if (files.length === 0) {
        alert("Please select at least one PDF.");
        return;
    }

    if (files.some(function (file) { return !isPdfFile(file); })) {
        alert("Only PDF files are supported.");
        return;
    }

    clearResults();
    showLoading("Uploading " + files.length + " invoice(s)...");

    const formData = new FormData();
    files.forEach(function (file) {
        formData.append("invoices", file);
    });

    try {
        const response = await fetch(url, {
            method: "POST",
            body: formData
        });
        const data = await readJson(response);

        if (!response.ok || !data.success) {
            throw new Error(responseError(data, response));
        }

        if (!Array.isArray(data.job_ids) || data.job_ids.length === 0) {
            throw new Error("The server did not return any jobs.");
        }

        showLoading("Processing " + data.job_ids.length + " invoice(s)...");
        const jobs = await waitForJobs(data.job_ids);

        hideLoading();
        renderInvoices(jobs);

        fileInput.value = "";
        showFileName(fileInput);
    } catch (error) {
        hideLoading();
        showError(error.message || "Upload failed.");
        console.error(error);
    }
}

async function waitForJobs(jobIds) {
    const deadline = Date.now() + POLL_TIMEOUT_MS;

    while (Date.now() < deadline) {
        const responses = await Promise.all(
            jobIds.map(function (id) {
                return fetch("/jobs/" + encodeURIComponent(id));
            })
        );

        const jobs = await Promise.all(
            responses.map(async function (response) {
                const data = await readJson(response);
                if (!response.ok || !data.success) {
                    throw new Error(responseError(data, response));
                }
                return data.job;
            })
        );

        const finished = jobs.filter(function (job) {
            return job.status === "COMPLETED" || job.status === "FAILED";
        }).length;

        showLoading(
            "Processing invoices... " + finished + "/" + jobs.length + " finished."
        );

        if (finished === jobs.length) {
            return jobs;
        }

        await sleep(POLL_INTERVAL_MS);
    }

    throw new Error("Timed out waiting for extraction results.");
}

/* ============================
   Render results (same design)
============================ */

function renderInvoices(jobs) {
    clearResults();

    const completed = jobs.filter(function (job) {
        return job.status === "COMPLETED";
    });
    const failed = jobs.filter(function (job) {
        return job.status === "FAILED";
    });

    if (completed.length > 0) {
        resultsContainer.appendChild(
            el(
                "div",
                "success",
                "✅ " + completed.length + " Invoice(s) extracted successfully."
            )
        );
    }

    if (failed.length > 0) {
        resultsContainer.appendChild(
            el(
                "div",
                "error",
                "❌ " + failed.length + " invoice(s) could not be processed."
            )
        );
    }

    jobs.forEach(function (job, index) {
        resultsContainer.appendChild(buildInvoiceCard(job, index));
    });
}

function statusBadge(pdfType) {
    const badge = el("span", null);

    if (pdfType === "Digital") {
        badge.textContent = "🟢 Digital PDF";
        badge.style.cssText =
            "background:#dcfce7;color:#166534;padding:4px 10px;" +
            "border-radius:20px;font-size:12px;font-weight:bold;";
    } else if (pdfType === "Mixed") {
        badge.textContent = "🔵 Mixed PDF";
        badge.style.cssText =
            "background:#dbeafe;color:#1e40af;padding:4px 10px;" +
            "border-radius:20px;font-size:12px;font-weight:bold;";
    } else if (pdfType) {
        badge.textContent = "🟠 Scanned PDF";
        badge.style.cssText =
            "background:#fef3c7;color:#92400e;padding:4px 10px;" +
            "border-radius:20px;font-size:12px;font-weight:bold;";
    } else {
        return null;
    }

    return badge;
}

function buildInvoiceCard(job, index) {
    const result = job.result || {};
    const invoice = result.invoice || {};
    const bodyId = "invoice-" + job.id;

    const card = el("div", "invoice-card");
    const header = el("div", "invoice-header");

    const left = el("div");
    left.appendChild(el("h3", null, "📄 " + job.filename));

    const meta = el("div");
    meta.style.cssText =
        "margin-top:8px; display:flex; gap:10px; align-items:center; flex-wrap:wrap;";

    if (job.status === "COMPLETED") {
        const ok = el("small", null, "✔ Extracted Successfully");
        ok.style.color = "green";
        meta.appendChild(ok);

        const badge = statusBadge(result.pdf_type);
        if (badge) {
            meta.appendChild(badge);
        }
    } else {
        const failed = el("small", null, "✖ Failed");
        failed.style.color = "#dc2626";
        meta.appendChild(failed);
    }

    left.appendChild(meta);
    header.appendChild(left);

    const body = el("div", "invoice-body");
    body.id = bodyId;

    if (job.status === "COMPLETED") {
        const viewButton = el("button", "view-btn", "View Extracted Info");
        viewButton.type = "button";
        viewButton.addEventListener("click", function () {
            toggleInvoice(bodyId, viewButton);
        });
        header.appendChild(viewButton);
        body.appendChild(buildProcessingSummary(result));
        body.appendChild(buildInvoiceTable(invoice));
    } else {
        body.style.display = "block";
        body.appendChild(
            el("div", "error", "❌ " + display(job.error))
        );
    }

    card.appendChild(header);
    card.appendChild(body);
    return card;
}

function tableRow(label, value) {
    const row = document.createElement("tr");
    row.appendChild(el("th", null, label));
    const cell = document.createElement("td");

    if (value instanceof Node) {
        cell.appendChild(value);
    } else {
        cell.textContent = display(value);
    }

    row.appendChild(cell);
    return row;
}

function buildProcessingSummary(result) {
    const wrapper = el("div");
    wrapper.style.cssText =
        "background:#f8fafc;border:1px solid #dbeafe;border-radius:8px;" +
        "padding:15px;margin-bottom:20px;";

    const title = el("h3", null, "📊 Processing Summary");
    title.style.cssText = "margin-bottom:12px;color:#1e40af;";
    wrapper.appendChild(title);

    const table = document.createElement("table");
    table.appendChild(tableRow("PDF Type", result.pdf_type));
    table.appendChild(tableRow("Approach Used", result.approach));
    table.appendChild(tableRow("Pages", result.page_count));

    const textTime = seconds(result.text_extraction_time);
    if (textTime) {
        table.appendChild(tableRow("Text Extraction", textTime));
    }

    const ocrTime = seconds(result.ocr_time);
    if (ocrTime) {
        table.appendChild(tableRow("OCR Time", ocrTime));
    }

    const uploadTime = seconds(result.upload_time);
    if (uploadTime) {
        table.appendChild(tableRow("Upload Time", uploadTime));
    }

    table.appendChild(tableRow("Gemini Time", seconds(result.gemini_time)));
    table.appendChild(tableRow("Total Time", seconds(result.total_time)));

    if (result.model) {
        table.appendChild(tableRow("Model", result.model));
    }

    wrapper.appendChild(table);
    return wrapper;
}

function buildInvoiceTable(invoice) {
    const table = document.createElement("table");
    const currency = invoice.currency || null;

    table.appendChild(tableRow("Supplier Name", invoice.supplier_name));
    table.appendChild(tableRow("Invoice Number", invoice.invoice_number));
    table.appendChild(tableRow("Invoice Date", invoice.invoice_date));
    table.appendChild(tableRow("Due Date", invoice.due_date));
    table.appendChild(tableRow("Supplier GSTIN", invoice.supplier_gstin));
    table.appendChild(tableRow("Customer Name", invoice.customer_name));
    table.appendChild(tableRow("Customer Address", invoice.customer_address));
    table.appendChild(tableRow("Customer GSTIN", invoice.customer_gstin));
    table.appendChild(tableRow("Currency", invoice.currency));
    table.appendChild(tableRow("Subtotal", money(invoice.subtotal, currency)));
    table.appendChild(tableRow("CGST", money(invoice.cgst, currency)));
    table.appendChild(tableRow("SGST", money(invoice.sgst, currency)));
    table.appendChild(tableRow("IGST", money(invoice.igst, currency)));
    table.appendChild(tableRow("Total Tax", money(invoice.total_tax, currency)));
    table.appendChild(tableRow("Invoice Total", money(invoice.invoice_total, currency)));
    table.appendChild(tableRow("Supplier Address", invoice.supplier_address));
    table.appendChild(tableRow("Bank Details", invoice.bank_details));

    const items = Array.isArray(invoice.items_purchased)
        ? invoice.items_purchased
        : [];
    const list = document.createElement("ul");

    if (items.length === 0) {
        list.appendChild(el("li", null, "Not Available"));
    } else {
        items.forEach(function (item) {
            list.appendChild(el("li", null, item));
        });
    }

    table.appendChild(tableRow("Items Purchased", list));
    return table;
}
