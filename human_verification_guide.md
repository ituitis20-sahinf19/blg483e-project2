# Human-in-the-Loop Verification Protocol for VibeCrawler

**Document Version:** 1.0
**Date:** 2023-10-27
**Prepared For:** Human-in-the-Loop Operator
**Purpose:** This document outlines the steps required for a Human-in-the-Loop operator to verify the functionality, environment conditions, and codebase readiness of the VibeCrawler staging environment prior to approval. The focus is on executing the localhost server, testing the API endpoints, and confirming expected system behavior.

---

## 1. Built Files Summary

The VibeCrawler system's core components are provided within a single Python script that combines the thread-safe data structures, the concurrent web crawler, and the localhost API server.

**Main Executable:**
*   `vibe_crawler.py`: This script contains all necessary classes (`ThreadSafeVisitedSet`, `ThreadSafeIndexMap`, `VibeCrawlerHTTPServer`, `VibeCrawlerRequestHandler`, `LinkAndTextExtractor`, `Crawler`) and the main execution block (`if __name__ == "__main__":`) to initialize and run the crawler and API server concurrently.

## 2. Executing the Localhost Server

Follow these instructions to start the VibeCrawler system, including the crawler and the API server.

### Prerequisites:
*   Python 3.x installed on the local machine.
*   The `vibe_crawler.py` script saved to your local directory.

### Instructions:

1.  **Open a Terminal or Command Prompt:** Navigate to the directory where you have saved `vibe_crawler.py`.

2.  **Execute the Script:** Run the Python script using the following command:
    ```bash
    python vibe_crawler.py
    ```

### Expected Console Output:
Upon successful execution, you should observe output similar to this:

```
--- Simulating Indexer Activity ---
Visited Set State: ThreadSafeVisitedSet(size=3)
Index Map State: ThreadSafeIndexMap(keywords=4, entries=5)
Frontier Queue Depth: 2

--- Simulating Direct Searcher Query ---
Search results for 'web': [('http://example.com/page1', 'http://example.com', 1), ('http://example.com/about', 'http://example.com', 2)]
Search results for 'nonexistent': []

--- Starting VibeCrawler Localhost API Server ---
Server will be accessible at http://127.0.0.1:8000
Dashboard: http://127.0.0.1:8000/dashboard
Search API: http://127.0.0.1:8000/search?q=web
Press Ctrl+C to stop the server.
Started 3 crawler workers.

--- Live Metrics ---
Visited URLs: 3
Indexed Keywords: 4
Indexed Entries: 5
Frontier Queue Depth: 2
# (These live metrics will update every 5 seconds, reflecting ongoing crawling activity)
# ...
```
*   The initial messages confirm the setup and simulated data loading.
*   The `Starting VibeCrawler Localhost API Server` message indicates the server is running on `http://127.0.0.1:8000`.
*   The `Started X crawler workers` message confirms the crawler is active.
*   The `Live Metrics` section will dynamically update, showing the crawler's progress (visited URLs, indexed keywords, queue depth).
*   The server will run until you press `Ctrl+C` in the terminal.

## 3. Testing the API with Postman (or cURL)

Use Postman or a command-line tool like cURL to interact with the running API server.

### 3.1. Verify Localhost Binding

Before testing, confirm the server is only accessible from `127.0.0.1`.
*   **Attempt Access from Another Machine (if possible):** If you try to access `http://<your-machine-ip>:8000` from another machine on the network, the connection should fail or time out. This confirms strict localhost binding.

### 3.2. Dashboard API Endpoint

This endpoint provides real-time system metrics.

*   **Endpoint:** `/dashboard`
*   **Method:** `GET`
*   **URL:** `http://127.0.0.1:8000/dashboard`

**Postman Request:**
*   Set request type to `GET`.
*   Enter `http://127.0.0.1:8000/dashboard` in the URL field.
*   Click `Send`.

**cURL Command:**
```bash
curl http://127.0.0.1:8000/dashboard
```

**Expected Response (JSON):**
You should receive a JSON response with metrics that update over time as the crawler processes URLs. The `crawler_status` should initially be `Running`.

```json
{
    "dashboard_metrics": {
        "visited_urls_count": 3,
        "indexed_keywords_count": 4,
        "indexed_entries_count": 5,
        "frontier_queue_depth": 2,
        "throttling_status": "Active (Crawler respects crawl_delay)",
        "crawler_status": "Running"
    }
}
```
*   **Verification:**
    *   Confirm the `Content-Type` header is `application/json`.
    *   Verify that `visited_urls_count`, `indexed_keywords_count`, `indexed_entries_count`, and `frontier_queue_depth` values are plausible and change (typically increase or decrease for queue depth) when you send multiple requests over time, indicating active crawling.
    *   Ensure `crawler_status` is `Running` while the crawler is active. If the crawler completes its queue, this should eventually change to `Idle/Stopped`.

### 3.3. Search API Endpoint

This endpoint allows querying the inverted index.

*   **Endpoint:** `/search`
*   **Method:** `GET`
*   **URL:** `http://127.0.0.1:8000/search?q=<keyword>` (replace `<keyword>` with your search term)

**Postman Request (Example for "web"):**
*   Set request type to `GET`.
*   Enter `http://127.0.0.1:8000/search?q=web` in the URL field.
*   Click `Send`.

**cURL Command (Example for "web"):**
```bash
curl "http://127.0.0.1:8000/search?q=web"
```
**Expected Response (JSON for "web"):**
You should receive a JSON response containing search results relevant to the keyword "web" from the (initially simulated and then crawled) index.

```json
{
    "query": "web",
    "results": [
        {
            "relevant_url": "http://example.com/page1",
            "origin_url": "http://example.com",
            "depth": 1
        },
        {
            "relevant_url": "http://example.com/about",
            "origin_url": "http://example.com",
            "depth": 2
        }
        // Additional results may appear here as the crawler populates the index
    ]
}
```

**Test for a Non-Existent Keyword (e.g., "nonexistent"):**
*   **URL:** `http://127.0.0.1:8000/search?q=nonexistent`

**cURL Command:**
```bash
curl "http://127.0.0.1:8000/search?q=nonexistent"
```

**Expected Response (JSON for "nonexistent"):**
An empty `results` list should be returned.
```json
{
    "query": "nonexistent",
    "results": []
}
```

*   **Verification:**
    *   Confirm the `Content-Type` header is `application/json`.
    *   Verify that searching for keywords known to be in the index (e.g., "web", "programming", "backend", or keywords from `example.com`) returns relevant results.
    *   Verify that searching for keywords not in the index returns an empty `results` list.
    *   Observe if new search results appear for existing keywords over time, indicating the crawler is actively indexing new content.
    *   Test for missing query parameter: `http://127.0.0.1:8000/search`. This should return a 400 Bad Request error with `{"error": "Missing query parameter \"q\""}`.

## 4. Approval of the Staging Codebase

Based on your observations during the execution and API testing, follow the procedure below for approval.

### Approval Criteria Checklist:

*   [ ] The `vibe_crawler.py` script executes successfully without critical errors.
*   [ ] The localhost API server starts and is accessible only from `127.0.0.1:8000`.
*   [ ] The Dashboard API (`/dashboard`) returns real-time metrics in JSON format.
*   [ ] Dashboard metrics (`visited_urls_count`, `indexed_keywords_count`, `frontier_queue_depth`, `crawler_status`) reflect active crawling and update dynamically.
*   [ ] The Search API (`/search?q=<keyword>`) returns accurate and relevant results for indexed keywords.
*   [ ] The Search API returns an empty `results` list for non-existent keywords.
*   [ ] The Search API handles missing `q` parameter gracefully with a 400 error.
*   [ ] The system can be gracefully stopped by pressing `Ctrl+C` in the terminal, resulting in "Server and Crawler gracefully stopped." message.
*   [ ] The crawler eventually completes its tasks (frontier queue becomes empty) and `crawler_status` switches to `Idle/Stopped` (or can be manually stopped).

### Approval Procedure:

1.  **Review Checklist:** Go through each item in the "Approval Criteria Checklist" above.
2.  **Record Findings:** Document any deviations from the expected behavior or any errors encountered.
3.  **Decision:**
    *   **Approve:** If all criteria in the checklist are met, the staging codebase is approved.
    *   **Reject:** If any critical criteria are not met, or significant issues are found, the staging codebase is rejected. Provide detailed notes on the reasons for rejection.

**Operator's Final Decision:**
*   **[  ] Approved for Production Deployment**
*   **[  ] Rejected - Requires Further Development**

**Operator Notes / Justification:**
*(Please provide detailed comments, especially if rejecting or if any minor issues were observed.)*
____________________________________________________________________________________________________
____________________________________________________________________________________________________
____________________________________________________________________________________________________

---

## 5. Troubleshooting Notes

*   **"Address already in use" error:** If you see an error indicating the port `8000` is already in use, it means another application is using that port.
    *   **Solution:** Close the application using port 8000, or modify `vibe_crawler.py` to use a different `PORT` (e.g., `8001`) and retry.
*   **No output from `curl` / Postman connection refused:**
    *   **Solution:** Ensure `vibe_crawler.py` is still running in its terminal. Check for any firewall rules that might be blocking access to port 8000 on `127.0.0.1`.
*   **Crawler not finding links/keywords:** The initial seed URLs (`google.com`, `bing.com`) are complex and may quickly hit depth limits or get throttled by those sites. `example.com` is a simpler site for testing. If the crawler seems stuck, ensure internet connectivity and that `example.com` is reachable. The `CRAWL_DELAY` can be adjusted, but be mindful of website policies.
*   **Performance:** The crawler's performance will depend on internet speed, website responsiveness, and the `CRAWL_DELAY` setting. Be patient as it processes URLs.