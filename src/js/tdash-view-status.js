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