# ---

**Product Requirements Document (PRD)**

**Project Name:** VibeCrawler

**Document Version:** 1.0

**Role / Persona:** Lead Project Manager (AI Orchestrator)

## **1\. Executive Summary**

The primary development methodology moves from manual coding to the Management of a Multi-Agent AI Team. The developer acts as the Lead Project Manager, overseeing specialized AI agents that collaborate to generate, verify, and refine the VibeCrawler system.

## **2\. Project Goals**

* **Demonstrate Architectural Sensibility:** Design a scalable, decoupled system where crawling and searching operate harmoniously.  
* **Master Concurrency Management:** Implement safe, lock-free, or appropriately synchronized data structures to handle simultaneous read/write operations.  
* **Validate Human-in-the-Loop Orchestration:** Successfully prompt, guide, and verify AI-generated code, ensuring it meets strict systemic constraints without hallucinating or defaulting to easy workarounds.

## **3\. Scope**

**In Scope:**

* A custom-built, recursive web crawler (Indexer).  
* A real-time query engine (Searcher) capable of searching while the indexer is active.  
* Thread-safe data storage mapping keywords to URLs.  
* Use of standard, language-native libraries only.
* Localhost deployment and execution for all interfaces, including the search API and system dashboard.

**Out of Scope:**

* Use of high-level scraping or crawling libraries (e.g., Scrapy, BeautifulSoup).  
* Production-grade distributed infrastructure (e.g., Kubernetes, external message brokers like Kafka—unless built natively).  
* Advanced NLP or PageRank algorithms for relevancy.

## ---

**4\. Functional Requirements**

### **4.1. Indexer (Web Crawler)**

The Indexer is responsible for discovering, fetching, and processing web pages.

* **F.1.1 Recursive Crawling:** The system must accept an origin URL and recursively crawl discovered links up to a user-defined maximum depth ($k$).  
* **F.1.2 Uniqueness Guarantee:** The system must implement a "Visited" data structure (e.g., a concurrent Set) to ensure no single URL is crawled or processed more than once.  
* **F.1.3 Back Pressure Management:** The crawler must regulate its own workload. It must implement mechanisms to manage load, such as enforcing a maximum rate of concurrent workers, connection pooling limits, or queue depth thresholds to prevent memory exhaustion and network rate-limiting.

### **4.2. Searcher (Query Engine)**

The Searcher is responsible for accepting user queries and returning ranked results from the live index.

* **F.2.1 Real-Time Querying:** The search engine must return a structured list of results formatted as a triple: (relevant\_url, origin\_url, depth).  
* **F.2.2 Live Indexing Support:** The query engine must be able to read from the index while the crawler is actively writing to it, without blocking the crawler or returning corrupted data.  
* **F.2.3 Relevancy Ranking:** The system must implement a baseline heuristic to rank search results. Acceptable heuristics include keyword frequency (Term Frequency) or HTML Title tag matching.

### **System Visibility & UI (Dashboard)**

* **Real-time Dashboard:** A dashboard must be built to monitor the exact state of the system in real-time as it runs. Whether this is built as a Command Line Interface (CLI) or a graphical web interface, it must be hosted locally and accessible entirely via localhost (127.0.0.1) on a specified port.

* **Metrics to Track:**

* Current Indexing Progress: The total number of URLs processed versus the count of URLs currently queued.
* Current Queue Depth: The live size of the Frontier Queue.
* Back-pressure/Throttling Status: An indicator showing if or when the system is actively throttling workers or holding back tasks due to load limits.

## ---

**5\. Technical & Non-Functional Requirements**

### **5.1. Concurrency and Thread Safety**

* **Constraint:** The system must be explicitly designed for concurrent execution.  
* **Implementation:** The Architect must direct the other agents to utilize thread-safe data structures. Depending on the chosen language, this includes Mutexes/Read-Write Locks, Channels (e.g., in Go), or Concurrent Maps (e.g., ConcurrentHashMap in Java or sync.Map in Go).  
* **Goal:** Zero data races or corruption during simultaneous read/write operations on the core index and the "Visited" set.

### **5.2. Native Focus (Zero-Dependency Constraint)**

* **Constraint:** The core logic for networking and HTML parsing must rely exclusively on language-native functionality (e.g., net/http and html packages in Go, or urllib and html.parser in Python).  
* **Goal:** Prove the Lead Project Manager's ability to instruct the agents to build foundational systems rather than relying on black-box external abstractions.

### **5.3. AI Orchestration Guidelines**

* **Agent Framework:** 
   
* System Architect:  Refines technical specs and ensures the modularity of the Indexer and Searcher components. Is also responsible from technical writing, providing documentation and roadmaps.
* Backend Engineer: Implements the core logic: recursive crawling, backpressure, and thread-safe data structures.
* QA / Security Auditor: Reviews code for race conditions and ensures the "Zero-Dependency" native constraint is met.
* DevOps Specialist: Focuses on the "Human-in-the-Loop" verification protocols and system integration testing.

* **Verification:** The Architect must perform "Human-in-the-Loop" verification for every major component generated, reviewing for race conditions, memory leaks, and adherence to the native-only constraint.

## **5.4. Execution Environment**

* **Constraint:** The entire application stack (Indexer, Searcher, API, and Dashboard) must be designed to run exclusively on localhost.

* **Goal:** Ensure the project remains a contained, locally executable assignment. The backend engineer must bind all web servers and API endpoints specifically to the local loopback address rather than exposing them publicly.

## ---

**6\. High-Level Architecture Flow**

1. **Seed Input:** User provides an Origin URL and Depth $k$.  
2. **Frontier Queue:** URL is pushed to a thread-safe queue.  
3. **Worker Pool:** A limited pool of concurrent workers pulls from the queue (handling Back Pressure).  
4. **Fetch & Parse:** Workers fetch the HTML (Native libraries only), extract links, and extract text/titles.  
5. **Filter:** Extracted links are checked against the concurrent "Visited" set. New links are pushed to the Frontier Queue with depth \+ 1\.  
6. **Index:** Parsed text is tokenized and written to a concurrent Inverted Index.  
7. **Search API:** A separate thread/process accepts user queries via a localhost endpoint, reads from the Inverted Index, calculates the Relevancy Heuristic, and returns the formatted Triples.

## ---

**7\. Multi-Agent Interaction Protocol**

* **Communication Flow:** The System Architect generates a technical task list based on the PRD. 
* The Backend Engineer receives tasks and generates Go/Python code using native-only libraries.
* The QA Auditor receives the output from the Backend Engineer to check for thread-safety violations (F.5.1) before the developer (Human-in-the-Loop) approves it.

* **Conflict Resolution:** If the QA Auditor identifies a potential data race in the Indexer's "Visited" set, it must provide a critique back to the Backend Engineer for a rewrite before the Human-in-the-Loop finalizes the code.

* **Evaluation Metric:** Success is measured by the QA Agent’s ability to confirm zero external dependencies and successful concurrent execution without manual developer intervention in the core logic.