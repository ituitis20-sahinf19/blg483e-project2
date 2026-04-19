# VibeCrawler Project Readme

## Project Name: VibeCrawler

## 1. Executive Summary

The VibeCrawler project introduces a custom-built, concurrent web crawling (Indexer) and real-time query engine (Searcher) system. Developed under a unique methodology emphasizing the Management of a Multi-Agent AI Team, this system demonstrates architectural sensibility, robust concurrency management, and strict adherence to a zero-dependency constraint. The human developer acts as a Lead Project Manager, guiding and verifying AI-generated code to meet high systemic standards, with a focus on modularity, scalability, and thread-safety.

## 2. Project Goals

*   **Demonstrate Architectural Sensibility:** Design a scalable, decoupled system where crawling and searching operate harmoniously.
*   **Master Concurrency Management:** Implement safe, lock-free, or appropriately synchronized data structures to handle simultaneous read/write operations.
*   **Validate Human-in-the-Loop Orchestration:** Successfully prompt, guide, and verify AI-generated code, ensuring it meets strict systemic constraints without hallucinating or defaulting to easy workarounds.

## 3. Scope

### In Scope:

*   A custom-built, recursive web crawler (Indexer).
*   A real-time query engine (Searcher) capable of searching while the indexer is active.
*   Thread-safe data storage mapping keywords to URLs.
*   Use of standard, language-native libraries only.
*   Localhost deployment and execution for all interfaces, including the search API and system dashboard.

### Out of Scope:

*   Use of high-level scraping or crawling libraries (e.g., Scrapy, BeautifulSoup).
*   Production-grade distributed infrastructure (e.g., Kubernetes, external message brokers like Kafka—unless built natively).
*   Advanced NLP or PageRank algorithms for relevancy.

## 4. High-Level Architecture Flow

The VibeCrawler system is designed with a clear, sequential yet highly concurrent flow, ensuring efficient web page discovery, indexing, and querying:

1.  **Seed Input:** The system initiates with a user-provided Origin URL and a maximum crawling Depth ($k$).
2.  **Frontier Queue:** The initial URL, along with its depth, is pushed to a thread-safe queue, which acts as the 'frontier' of URLs yet to be crawled.
3.  **Worker Pool:** A limited pool of concurrent workers continuously pulls URLs from the Frontier Queue. This pool inherently manages backpressure, ensuring the system operates within configured load limits.
4.  **Fetch & Parse:** Each worker fetches the HTML content of a URL using native HTTP capabilities. It then parses the HTML to extract internal and external links, and the visible text content.
5.  **Filter & Queue:** Extracted links are normalized and checked against a concurrent "Visited" set to guarantee uniqueness. New, unvisited links (within the maximum depth) are then pushed back to the Frontier Queue with an incremented depth.
6.  **Index:** The parsed text from each page is tokenized into keywords. These keywords, along with the relevant URL, its origin, and depth, are written to a concurrent Inverted Index.
7.  **Search API:** A separate, concurrently running thread manages a localhost API. This API accepts user queries, reads from the live Inverted Index, applies a baseline relevancy heuristic, and returns formatted results (relevant\_url, origin\_url, depth).

This architecture ensures a decoupled and scalable system where indexing and searching can occur simultaneously without conflicts, thanks to robust concurrency management.

## 5. Core Components

The VibeCrawler system is built around several key modular components, all adhering to the zero-dependency constraint:

### 5.1. ThreadSafeVisitedSet

*   **Purpose:** Ensures the "Uniqueness Guarantee" (F.1.2) by keeping track of all URLs that have already been crawled or are currently in the process. This prevents redundant work and infinite loops.
*   **Implementation:** Utilizes Python's native `set` for efficient membership testing and storage, protected by a `threading.Lock` to ensure thread-safe `add()` and `contains()` operations. This design prevents race conditions during concurrent updates from multiple crawler workers.

### 5.2. ThreadSafeIndexMap

*   **Purpose:** Serves as the core data store for the inverted index, mapping keywords to a list of `(relevant_url, origin_url, depth)` triples. This enables the "Real-Time Querying" (F.2.1) and "Live Indexing Support" (F.2.2) requirements.
*   **Implementation:** Uses a Python `dict` as the underlying structure, guarded by a `threading.Lock`. The `add()` method atomicity is guaranteed, and the `search()` method safely returns a *copy* of the results list to prevent external modification of the internal index while the lock is released, ensuring data integrity for concurrent readers and writers.

### 5.3. Crawler (Indexer Logic)

*   **Purpose:** Responsible for the "Recursive Crawling" (F.1.1) process, discovering, fetching, parsing, and processing web pages.
*   **Implementation:**
    *   **Networking:** Employs Python's native `urllib.request` for fetching web content, adhering strictly to the "Native Focus" (5.2) constraint.
    *   **Parsing:** Uses `html.parser.HTMLParser` to extract links and text content from HTML, again, without external libraries.
    *   **Keyword Extraction:** A simple, native regex-based tokenizer extracts keywords from page text.
    *   **Concurrency & Backpressure:** Manages a pool of `worker_thread`s that pull tasks from a `queue.Queue` (which is inherently thread-safe). It implements "Back Pressure Management" (F.1.3) through a configurable `crawl_delay_seconds` between requests per worker, preventing network overload and rate-limiting.
    *   **State Management:** Integrates with `ThreadSafeVisitedSet` and `ThreadSafeIndexMap` for managing visited URLs and indexed content, respectively.

### 5.4. Searcher (Query Engine & Localhost API)

*   **Purpose:** Provides a "Real-Time Querying" (F.2.1) interface via a local web server and offers "System Visibility & UI (Dashboard)" for monitoring.
*   **Implementation:**
    *   **API Server:** Built using Python's native `http.server` and `socketserver.ThreadingMixIn` to create a multi-threaded HTTP server that runs exclusively on `127.0.0.1` (localhost) as per the "Execution Environment" (5.4) constraint.
    *   **Request Handler:** `VibeCrawlerRequestHandler` processes incoming `GET` requests for two primary endpoints:
        *   `/search?q=<keyword>`: Queries the `ThreadSafeIndexMap` and returns results formatted as `(relevant_url, origin_url, depth)` triples. It implements a baseline relevancy heuristic (keyword frequency/presence) by default.
        *   `/dashboard`: Provides real-time metrics on crawling progress, queue depth, and throttling status, fulfilling the dashboard requirements.

## 6. Zero-Dependency Constraint

A cornerstone of the VibeCrawler project is its strict "Zero-Dependency Constraint" (5.2). This means the core logic for networking, HTML parsing, and all data structures must rely exclusively on language-native functionality.

**Compliance Status:**
The **QA / Security Auditor** has confirmed that the system is **Compliant** with this constraint. All modules used (`threading`, `http.server`, `socketserver`, `json`, `urllib.parse`, `queue`, `time`, `urllib.request`, `urllib.error`, `html.parser`, `re`) are integral parts of the Python Standard Library. No external third-party libraries are used.

## 7. Concurrency Management

"Master Concurrency Management" (2. Project Goals) is achieved through a meticulous design focused on thread-safe data structures and concurrent processing:

*   **Shared Data Structures:** Both `ThreadSafeVisitedSet` and `ThreadSafeIndexMap` leverage `threading.Lock()` to ensure that all read and write operations on their internal states are atomic and mutually exclusive. This prevents any form of data corruption or race conditions, even under heavy concurrent load from multiple crawler workers and search queries.
*   **Frontier Queue:** The `queue.Queue` from Python's standard library is inherently thread-safe, making it a perfect fit for the crawler's frontier, allowing multiple workers to safely `put()` and `get()` URLs without explicit locking.
*   **API Server:** `socketserver.ThreadingMixIn` is employed to enable the HTTP server to handle multiple incoming `/search` and `/dashboard` requests concurrently, without blocking the crawler or each other. Each request is processed in its own thread, safely interacting with the shared, locked data structures.
*   **Crawler Workers:** The `Crawler` orchestrates a fixed pool of worker threads, each independently fetching and processing URLs. `threading.Event` and `threading.Semaphore` are used for robust worker orchestration and graceful shutdown.

The **QA / Security Auditor** has thoroughly reviewed the implementation and confirmed **no race conditions** were detected in the core data structures or their interactions, affirming the robust concurrency design.

## 8. How to Run Locally

This section provides instructions to set up and run the VibeCrawler system, including the web crawler and the localhost API server.

### Prerequisites:

*   **Python 3.x:** Ensure you have Python 3.x installed on your system.
*   **`vibe_crawler.py`:** Download or create the `vibe_crawler.py` file containing all the provided code.

### Instructions:

1.  **Open a Terminal or Command Prompt:**
    Navigate to the directory where you have saved `vibe_crawler.py`.

2.  **Execute the Script:**
    Run the Python script using the following command:
    ```bash
    python vibe_crawler.py
    ```

### Expected Console Output:

Upon successful execution, the console will display initialization messages, simulated data, and then continuously update with live metrics. The server will start on `http://127.0.0.1:8000`.

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
Visited URLs: <count_1>
Indexed Keywords: <count_2>
Indexed Entries: <count_3>
Frontier Queue Depth: <count_4>
# (These live metrics will update every 5 seconds, reflecting ongoing crawling activity)
# ...
```

*   The `--- Live Metrics ---` section will dynamically update, showing the crawler's progress.
*   The server will run until you press `Ctrl+C` in the terminal, which will trigger a graceful shutdown of both the server and crawler workers.

### Testing the API Endpoints (Using `curl`):

The VibeCrawler API is strictly bound to `127.0.0.1` (localhost) on port `8000`.

#### 1. Verify Localhost Binding:
If you attempt to access `http://<your-machine-ip>:8000` from another machine on the network, the connection should fail or time out. This confirms strict localhost binding as required.

#### 2. Dashboard API Endpoint:
This endpoint provides real-time system metrics.

*   **URL:** `http://127.0.0.1:8000/dashboard`
*   **Method:** `GET`

```bash
curl http://127.0.0.1:8000/dashboard
```

**Expected Response (JSON):**
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
*   **Verification:** Confirm that the metrics reflect active crawling and update dynamically with subsequent requests. `crawler_status` should be `Running` initially.

#### 3. Search API Endpoint:
This endpoint allows querying the inverted index.

*   **URL:** `http://127.0.0.1:8000/search?q=<keyword>`
*   **Method:** `GET`

**Example 1: Searching for "web"**
```bash
curl "http://127.0.0.1:8000/search?q=web"
```

**Expected Response (JSON):**
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

**Example 2: Searching for a non-existent keyword (e.g., "nonexistent")**
```bash
curl "http://127.0.0.1:8000/search?q=nonexistent"
```

**Expected Response (JSON):**
```json
{
    "query": "nonexistent",
    "results": []
}
```

**Example 3: Query with missing parameter**
```bash
curl "http://127.0.0.1:8000/search"
```

**Expected Response (JSON):**
```json
{"error": "Missing query parameter \"q\""}
```
*   **Verification:** Ensure relevant results are returned for indexed keywords, an empty list for non-existent ones, and appropriate error handling for missing parameters.

## 9. Verification and Testing

The VibeCrawler system has undergone rigorous verification as part of the Human-in-the-Loop Orchestration.

*   **QA Audit Report:** A comprehensive "Audit Report: VibeCrawler System" was generated by the **QA / Security Auditor**. This report confirmed:
    *   **Zero Race Conditions:** Detailed analysis of `ThreadSafeVisitedSet`, `ThreadSafeIndexMap`, and `queue.Queue` usage confirmed robust thread-safety and the absence of data races.
    *   **Zero-Dependency Compliance:** Verified that all imported modules are part of the Python Standard Library, strictly adhering to the constraint.
    *   **Localhost Binding:** Confirmed that the API endpoints are correctly bound to `127.0.0.1` only.
*   **Human-in-the-Loop Verification Protocol:** The "Human-in-the-Loop Verification Protocol" outlines a detailed checklist for operators to:
    *   Execute the system locally.
    *   Test both the `/dashboard` and `/search` API endpoints.
    *   Observe dynamic metrics and search results.
    *   Confirm graceful shutdown.

These verification steps collectively ensure the functionality, stability, and adherence to technical constraints of the VibeCrawler system.

## 10. Troubleshooting Notes

*   **"Address already in use" error:** If port `8000` is already in use, close the conflicting application or modify the `PORT` variable in `vibe_crawler.py` (e.g., to `8001`).
*   **No output from `curl` / Postman connection refused:** Ensure `vibe_crawler.py` is still running in its terminal. Check for any firewall rules blocking port `8000` on `127.0.0.1`.
*   **Crawler not finding links/keywords / Stuck Crawler:**
    *   Ensure internet connectivity.
    *   The `CRAWL_DELAY` (default 0.5 seconds) introduces a pause between requests to prevent overwhelming websites. Adjust this if necessary, but be mindful of website policies.
    *   Initial seed URLs like `google.com` or `bing.com` might be aggressively throttled by their servers; `example.com` is a good, simpler test site.
    *   The `MAX_CRAWL_DEPTH` also limits how far the crawler will go.
*   **Performance:** Crawler performance depends on network speed, server responsiveness of target websites, and `CRAWL_DELAY`. Be patient as it processes URLs.