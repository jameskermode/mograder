"""Anywidget button that shows a browser confirm() dialog before firing."""

from __future__ import annotations

import anywidget
import traitlets


class ConfirmButton(anywidget.AnyWidget):
    """A button that prompts with confirm() before updating its value.

    Use with ``mo.ui.anywidget(ConfirmButton(...), on_change=callback)``
    to get a reactive button that only fires after user confirmation.
    """

    _esm = """
    function render({ model, el }) {
        const btn = document.createElement("button");
        btn.textContent = model.get("label");
        btn.style.cssText = `
            padding: 4px 12px;
            background: #dc3545;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.875rem;
            font-family: inherit;
        `;
        btn.addEventListener("mouseenter", () => { btn.style.background = "#b02a37"; });
        btn.addEventListener("mouseleave", () => { btn.style.background = "#dc3545"; });
        btn.addEventListener("click", () => {
            if (confirm(model.get("message"))) {
                model.set("count", model.get("count") + 1);
                model.save_changes();
            }
        });
        el.appendChild(btn);
    }
    export default { render };
    """
    count = traitlets.Int(0).tag(sync=True)
    label = traitlets.Unicode("Reset").tag(sync=True)
    message = traitlets.Unicode("Are you sure?").tag(sync=True)
    assignment = traitlets.Unicode("").tag(sync=True)
