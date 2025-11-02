/*
 * Client-side code to support interactivity on the challenge page.
 * This script:
 *   - Initializes the third-party (ACE) editor component to allow the user to create
 *     a submission. ACE provides syntax highlighting, auto-indent, etc.
 *   - Contains the glue required to properly POST a submission to the server and
 *     redirect to its page after it is created.
 *   - Contains glue to load a submission from a file.
 */

const editor = ace.edit("editor");
editor.setTheme("ace/theme/xcode");
editor.session.setMode("ace/mode/python");
editor.setOptions({
	fontFamily: "'Latin Modern Mono', monospace",
	fontSize  : "12pt",
});

// If a template exists, the server-side rendering engine will leave it in window.data
if (window.data.hasOwnProperty("template"))
	editor.session.setValue(window.data.template);

document.getElementById("submit").addEventListener("click", () => {
	fetch(`${document.location.pathname}/submit`, {
		method : "POST",
		headers: {
			"Content-Type": "application/json",
			"X-CSRF-Token": window.data.csrfToken,
		},
		body   : JSON.stringify({ code: editor.getValue() }),
	}).then((response) => {
		if (!response.ok)
			response.text().then((text) => {
				alert(text);
			});
		else
			response.json().then((data) => {
				window.location.assign(`${document.location.pathname}/submission/${data.id}`);
			});
	}).catch((error) => {
		alert(error.message);
	});
});

document.getElementById("load-from-file").addEventListener("click", () => {
	// The only way to display a file picker from JS is with a fake input element
	const fileInput = document.createElement("input");
	fileInput.type = "file";
	fileInput.accept = ".py";
	fileInput.addEventListener("change", () => {
		fileInput.files[0].text().then((text) => {
			editor.session.setValue(text);
		});
	});
	fileInput.click();
});
