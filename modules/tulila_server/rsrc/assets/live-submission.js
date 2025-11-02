/*
 * Monitor an ongoing submission.
 *
 * Tulila Server will allow one WebSocket connection to receive events from a submission
 * that is currently running; this script receives these events and formats them for display.
 *
 * Note that Tulila Server only allows a single WebSocket connection to monitor a submission
 * at a time; thus, this script may be running in at most one tab.
 */

// WebSocket close reason codes; 400x are mine
const ANOTHER_CLIENT_CONNECTED = 4001;
const ABNORMAL_CLOSURE = 1006;
const FINAL_RESULTS_READY = 4002;

const connectionStatus = document.getElementById("connection-status");
const log = document.getElementById("log");

const socket = new WebSocket(`${document.location.pathname}/events`);

/*
 * Sometimes, the socket closes or fails to open not because of a real error, but merely
 * because the submission has finished running and it is only possible to monitor a
 * pending submission. Handle this gracefully by reloading - the server will send back
 * the "complete submission" page (which doesn't have this script).
 */
function ifCompleteReloadElse(f) {
	fetch(`${document.location.pathname}/is_complete`)
		.then((response) => response.json())
		.then((data) => {
			if (data.is_complete) {
				window.reloading = true;
				window.location.reload();
			} else
				f();
		}).catch((e) => {
			if (window.reloading !== true)
				f();
		});
}

socket.addEventListener("close", (ev) => {
	connectionStatus.setAttribute("class", "badge negative");
	connectionStatus.textContent = "Disconnected";
	if (ev.code === ANOTHER_CLIENT_CONNECTED)
		alert("The connection was closed because you opened this page in another tab.");
	else if (ev.code === ABNORMAL_CLOSURE)
		ifCompleteReloadElse(() => alert("The connection was closed due to a network error."));
	else if (ev.code === FINAL_RESULTS_READY)
		window.location.reload();
});

socket.addEventListener("error", (ev) => {
	ifCompleteReloadElse(() => alert("Unable to connect to WebSocket!"));
});

socket.addEventListener("message", (ev) => {
	const createSpan = (klass, text) => {
		const el = document.createElement("span");
		el.setAttribute("class", klass);
		el.textContent = text;
		return el;
	};
	const data = JSON.parse(ev.data);
	log.appendChild(document.createTextNode(`[${data.timestamp.toFixed(6)}] `));
	log.appendChild(createSpan("agent-name", `${data.agent_name}: `));
	if (data.is_diagnostic) {
		log.appendChild(createSpan("warning", "WARNING: "));
		log.appendChild(createSpan("diagnostic", data.line));
	} else {
		log.appendChild(document.createTextNode(data.line));
	}
	log.appendChild(document.createTextNode("\n"));
});

socket.addEventListener("open", (ev) => {
	connectionStatus.setAttribute("class", "badge positive");
	connectionStatus.textContent = "Connected";
});
