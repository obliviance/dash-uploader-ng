# Styling

## The component cannot restyle your app

Every rule in the bundled stylesheets is scoped beneath `.dash-uploader-root`, a
class that is always present on the component's root element.

This was not true upstream. The bundled Bootstrap 4 rules (`.btn`, `.progress`,
and even a bare `progress` element selector) were injected into `<head>`
unscoped, so simply importing the component restyled buttons and icon fonts
elsewhere on the page — reported over four years as
[#91](https://github.com/fohrloop/dash-uploader/issues/91) (breaks Font
Awesome), [#43](https://github.com/fohrloop/dash-uploader/issues/43) (restyles
unrelated buttons) and several others, without the shared cause being found.

`.dash-uploader-root` is added alongside whatever you pass as `className`, so
overriding `className` does not remove the scoping.

## Class reference

Answering [#25](https://github.com/fohrloop/dash-uploader/issues/25). All of
these are stable and safe to target from your own stylesheet.

### Root element

| Class | Applied when |
| ----- | ------------ |
| `dash-uploader-root` | Always. The scoping anchor — don't rely on it for appearance |
| `dash-uploader-default` | Always (override with the `className` prop) |
| `dash-uploader-hovered` | A file is being dragged over the drop zone |
| `dash-uploader-uploading` | An upload is in progress |
| `dash-uploader-paused` | The upload is paused |
| `dash-uploader-completed` | The upload finished |
| `dash-uploader-disabled` | The component is disabled |

The state classes are configurable via the `hoveredClass`, `uploadingClass`,
`pausedClass`, `completedClass` and `disabledClass` props.

### Inside the component

| Class | Element |
| ----- | ------- |
| `dash-uploader-label` | The text label ("Drag and Drop Here to upload!") |
| `dash-uploader-button-container` | Wrapper around the cancel/pause/start buttons |
| `dash-uploader-btn` | Default class on each button |
| `dash-uploader-btn-start` | Start button |
| `dash-uploader-btn-cancel` | Cancel button |
| `dash-uploader-btn-pause` | Pause button |
| `dash-uploader-progress-value` | The percentage text on the progress bar |

## Recipes

Because every bundled rule is scoped, your own rules need no special
specificity — but they must be at least as specific to win. Prefixing with
`.dash-uploader-root` is the reliable way:

**Center the progress percentage** — [#81](https://github.com/fohrloop/dash-uploader/issues/81):

```css
.dash-uploader-root .dash-uploader-progress-value {
    left: 0;
    right: 0;
    margin: 0 auto;
    text-align: center;
}
```

**Restyle the buttons without touching the rest of your app:**

```css
.dash-uploader-root .dash-uploader-btn {
    border-radius: 0;
    font-weight: 600;
}
```

**Change the drop zone's appearance:**

```python
du.Upload(
    default_style={
        "borderStyle": "solid",
        "borderColor": "#0d6e70",
        "minHeight": "160px",
        "lineHeight": "160px",
    },
)
```

`default_style` is merged over the component's defaults, so you only need to
supply the properties you want to change.

## Known limitation

Supplying arbitrary Dash components as children of the drop zone — rather than
a plain text string — is not supported yet
([#47](https://github.com/fohrloop/dash-uploader/issues/47)). It is tracked in
[ROADMAP.md](../ROADMAP.md) under theme 2.
