export function resolveNetworkInstance(filenames, capabilities) {
  const instances = filenames
    .map((filename) => ({
      filename,
      ...capabilities?.files?.[filename]?.networkInstance,
    }))
    .filter((instance) => Object.keys(instance).length > 1);
  const known = new Set(instances.map((instance) => instance.extPanId?.toLowerCase()).filter(Boolean));
  if (known.size > 1) {
    return {
      status: "mixed",
      extPanId: null,
      provenance: "mixed",
      sources: instances.filter((instance) => instance.extPanId).map((instance) => instance.filename),
    };
  }
  if (!instances.length) {
    return { status: "unknown", extPanId: null, provenance: "unknown", sources: [] };
  }
  const scope = instances.find((item) => item.extPanId && item.provenance === "observed")
    ?? instances.find((item) => item.extPanId) ?? instances[0];
  return {
    status: scope.extPanId ? "known" : "unknown",
    extPanId: scope.extPanId ?? null,
    provenance: scope.provenance ?? "unknown",
    sources: instances.filter((instance) =>
      !scope.extPanId || instance.extPanId?.toLowerCase() === scope.extPanId.toLowerCase(),
    ).map((instance) => instance.filename),
  };
}

export function networkInstanceStatus(filenames, capabilities) {
  const scope = resolveNetworkInstance(filenames, capabilities);
  if (scope.status === "mixed") return "Network instance: mixed";
  if (!scope.extPanId) return "Network instance: unknown";
  return `Network instance: ${scope.extPanId} (${scope.provenance})`;
}

export function networkInstanceMatchesId(filenames, capabilities, networkId) {
  const expectedExtPanId = networkId?.match(/^extpan:([0-9a-f]{16})$/i)?.[1];
  if (!expectedExtPanId) return false;
  const scope = resolveNetworkInstance(filenames, capabilities);
  return scope.status === "known"
    && scope.extPanId?.toLowerCase() === expectedExtPanId.toLowerCase();
}

export function createViewStatusOwner(presentStatus = () => {}) {
  let activeView = null;
  let datasetToken = null;
  const statusByView = new Map();

  function setDataset(nextDatasetToken) {
    if (datasetToken === nextDatasetToken) return;
    datasetToken = nextDatasetToken;
    statusByView.clear();
  }

  return {
    activate(view, nextDatasetToken) {
      setDataset(nextDatasetToken);
      activeView = view;
      const status = statusByView.get(view);
      if (status !== undefined) presentStatus(status);
      return status;
    },
    publish(view, status, sourceDatasetToken) {
      if (sourceDatasetToken !== datasetToken) return false;
      statusByView.set(view, status);
      if (view === activeView) presentStatus(status);
      return true;
    },
    invalidate(nextDatasetToken = null) {
      datasetToken = nextDatasetToken;
      statusByView.clear();
    },
  };
}

let presenter = () => {};
const viewStatusOwner = createViewStatusOwner((status) => presenter(status));

export function configureViewStatusPresenter(nextPresenter) {
  presenter = typeof nextPresenter === "function" ? nextPresenter : () => {};
}

export function supersedeViewStatus(status) {
  presenter(status);
}

export function activateViewStatus(view, datasetToken) {
  return viewStatusOwner.activate(view, datasetToken);
}

export function publishViewStatus(view, status, datasetToken) {
  return viewStatusOwner.publish(view, status, datasetToken);
}

export function invalidateViewStatuses(datasetToken = null) {
  viewStatusOwner.invalidate(datasetToken);
}