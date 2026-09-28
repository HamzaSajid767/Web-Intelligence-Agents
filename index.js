/**
 * Lead Finder scraper — run in browser console on the People Finder results page.
 *
 * WHAT IT DOES
 *  - Reads every visible row on the current page: Name, Title, Company, Company Domain,
 *    Business Type, Location.
 *  - Does NOT capture email — the email field is masked client-side and the real address
 *    is not present in the DOM until unlocked, so any "scraped" email would be fake.
 *  - Checks whether the "Next page" button is disabled (i.e. last page reached).
 *  - If enabled: waits a random 10–15s, clicks Next, waits for the table to actually
 *    change (not just a fixed timer) before scraping again — this guards against
 *    silently re-scraping a stale page if a load is slow.
 *  - When pagination ends (or you stop it), triggers a CSV download automatically.
 *
 * USAGE
 *  1. Open devtools console on the results page.
 *  2. Paste this whole script, hit enter.
 *  3. Call:  await scrapeAllPages()
 *  4. To stop early without losing data so far: call  stopScrape()  then it will
 *     finish the current page and download whatever was captured.
 *
 * NOTES / LIMITATIONS (read before relying on this)
 *  - This only works on whatever the DOM currently renders. If the site lazy-loads
 *    rows on scroll within a page (in addition to pagination), this script as-is
 *    will only catch what's rendered at scrape time — let me know if that's the case
 *    and the row-selection logic needs to scroll-and-wait instead.
 *  - Selector strategy is structural (row > cell position), not class-name based,
 *    because utility classes here are non-semantic and likely unstable across
 *    deploys. If the table column ORDER changes, this breaks. Validate row 1 of
 *    output against the page after first page scrape before trusting the whole run.
 *  - This respects whatever page you're already authorized to view. It does not
 *    click "Reveal emails," does not call APIs directly, and does not attempt to
 *    bypass the unlock/credit gate.
 */

(function () {
    let STOP_REQUESTED = false;
    window.stopScrape = () => {
      STOP_REQUESTED = true;
      console.log('[scraper] Stop requested — will finish current page, then download CSV.');
    };
  
    const FIELDS = ['name', 'title', 'company', 'companyDomain', 'businessType', 'location'];
  
    function randomDelay(minMs, maxMs) {
      return new Promise((resolve) => {
        const ms = Math.floor(Math.random() * (maxMs - minMs + 1)) + minMs;
        console.log(`[scraper] Waiting ${(ms / 1000).toFixed(1)}s before next page...`);
        setTimeout(resolve, ms);
      });
    }
  
    function getRows() {
      // Each lead row is a <tr> inside the results <tbody>. We find the table by
      // looking for the header row that contains "Name" / "Company" text, then
      // take its parent table's tbody rows. This is more resilient than hardcoding
      // a utility-class chain.
      const headerCell = Array.from(document.querySelectorAll('th')).find(
        (th) => th.textContent.trim().toLowerCase() === 'name'
      );
      if (!headerCell) return [];
      const table = headerCell.closest('table');
      if (!table) return [];
      const tbody = table.querySelector('tbody');
      if (!tbody) return [];
      return Array.from(tbody.querySelectorAll('tr'));
    }
  
    function cellText(row, columnIndex) {
      const cells = row.querySelectorAll('td');
      const cell = cells[columnIndex];
      if (!cell) return '';
      // Strip the external-link icon's own text (it has none, but be defensive)
      // and just grab the visible text content, collapsing whitespace.
      return cell.textContent.replace(/\s+/g, ' ').trim();
    }
  
    function extractDomain(row, companyColumnIndex) {
      const cells = row.querySelectorAll('td');
      const companyCell = cells[companyColumnIndex];
      if (!companyCell) return '';
      const link = companyCell.querySelector('a[href]');
      if (!link) return '';
      try {
        const url = new URL(link.getAttribute('href'));
        return url.hostname.replace(/^www\./, '');
      } catch (e) {
        return link.getAttribute('href') || '';
      }
    }
  
    function scrapeCurrentPage() {
      const rows = getRows();
      const results = [];
  
      // Column order per the markup: [checkbox, Name, Title, Company, Business type, Location, Email]
      // Email column (index 6) is intentionally skipped per your instruction.
      const COL = {
        name: 1,
        title: 2,
        company: 3,
        businessType: 4,
        location: 5,
      };
  
      for (const row of rows) {
        const name = cellText(row, COL.name);
        // Skip rows that don't look like data rows (e.g. empty/placeholder rows)
        if (!name) continue;
  
        results.push({
          name,
          title: cellText(row, COL.title) || '-',
          company: cellText(row, COL.company) || '-',
          companyDomain: extractDomain(row, COL.company) || '-',
          businessType: cellText(row, COL.businessType) || '-',
          location: cellText(row, COL.location) || '-',
        });
       
      }
    
      return results;
    }
  
    function getNextButton() {
      return document.querySelector('button[aria-label="Next page"]');
    }
  
    function nextButtonEnabled() {
      const btn = getNextButton();
      if (!btn) return false;
      return !btn.disabled && btn.getAttribute('aria-disabled') !== 'true';
    }
  
    function tableSignature(rows) {
      // Cheap hash of current page content so we can confirm the page actually
      // changed after clicking Next, rather than trusting the delay blindly.
      return rows.map((r) => cellText(r, 1) + '|' + cellText(r, 3)).join('::');
    }
  
    async function waitForPageChange(previousSignature, maxWaitMs = 8000, pollMs = 300) {
      const start = Date.now();
      while (Date.now() - start < maxWaitMs) {
        const rows = getRows();
        const sig = tableSignature(rows);
        if (sig && sig !== previousSignature) {
          return true;
        }
        await new Promise((r) => setTimeout(r, pollMs));
      }
      return false; // timed out — page may not have changed
    }
  
    function downloadCSV(allResults) {
      if (allResults.length === 0) {
        console.warn('[scraper] No results captured — skipping CSV download.');
        return;
      }
      const header = ['Name', 'Title', 'Company', 'Company Domain', 'Business Type', 'Location'];
      const escapeCsv = (val) => {
        const s = String(val ?? '');
        if (/[",\n]/.test(s)) {
          return '"' + s.replace(/"/g, '""') + '"';
        }
        return s;
      };
  
      const lines = [header.join(',')];
      for (const r of allResults) {
        lines.push(
          [r.name, r.title, r.company, r.companyDomain, r.businessType, r.location]
            .map(escapeCsv)
            .join(',')
        );
      }
  
      const csvContent = lines.join('\n');
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
      a.href = url;
      a.download = `leads_export_${timestamp}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      console.log(`[scraper] Downloaded CSV with ${allResults.length} leads.`);
    }
  
    window.scrapeAllPages = async function scrapeAllPages(options = {}) {
      STOP_REQUESTED = false;
      const minDelay = options.minDelayMs ?? 10000;
      const maxDelay = options.maxDelayMs ?? 15000;
      const maxPages = options.maxPages ?? Infinity;
  
      const allResults = [];
      let pageNum = 1;
  
      while (true) {
        console.log(`[scraper] Scraping page ${pageNum}...`);
        const rowsBefore = getRows();
        const pageResults = scrapeCurrentPage();
        console.log(`[scraper] Page ${pageNum}: captured ${pageResults.length} leads.`);
        allResults.push(...pageResults);
  
        if (STOP_REQUESTED) {
          console.log('[scraper] Stop flag set — finishing now.');
          break;
        }
        if (pageNum >= maxPages) {
          console.log(`[scraper] Reached maxPages limit (${maxPages}).`);
          break;
        }
  
        const enabled = nextButtonEnabled();
        console.log(`[scraper] Next button enabled: ${enabled}`);
        if (!enabled) {
          console.log('[scraper] Next button disabled — assuming last page reached.');
          break;
        }
  
        await randomDelay(minDelay, maxDelay);
  
        const prevSig = tableSignature(rowsBefore);
        const nextBtn = getNextButton();
        nextBtn.click();
  
        const changed = await waitForPageChange(prevSig);
        if (!changed) {
          console.warn(
            '[scraper] Page content did not appear to change after clicking Next ' +
            'within the timeout. Stopping to avoid duplicate/stale scrape — check ' +
            'the page manually.'
          );
          break;
        }
  
        pageNum++;
      }
  
      console.log(`[scraper] Done. Total leads captured: ${allResults.length}`);
      downloadCSV(allResults);
      return allResults;
    };
  
    console.log(
      '[scraper] Loaded. Run: await scrapeAllPages()  |  Stop early: stopScrape()'
    );
  })();


//  await scrapeAllPages({ maxPages: 2 }); 