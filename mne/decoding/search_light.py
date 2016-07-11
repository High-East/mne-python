# Author: Jean-Remi King <jeanremi.king@gmail.com>
#
# License: BSD (3-clause)

import numpy as np

from .mixin import TransformerMixin
from .base import BaseEstimator  # XXX reorganize sklearn objects.
from ..parallel import parallel_func


class SearchLight(BaseEstimator, TransformerMixin):
    """Search Light.

    Fit, predict and score a series of models to each subset of the dataset
    along the third dimension.

    Parameters
    ----------
    base_estimator : object
        The base estimator to iteratively fit on a subset of the dataset.
    n_jobs : int, optional (default=1)
        The number of jobs to run in parallel for both `fit` and `predict`.
        If -1, then the number of jobs is set to the number of cores.
    """
    def __init__(self, base_estimator, n_jobs=1):
        self.base_estimator = base_estimator
        self.n_jobs = n_jobs
        if not isinstance(self.n_jobs, int):
            raise ValueError('n_jobs must be int, got %s' % n_jobs)

    def fit_transform(self, X, y):
        """
        Fit and transform a series of independent estimators to the dataset.

        Parameters
        ----------
        X : array, shape (n_samples, n_features, n_estimators)
            The training input samples. For each data slice, a clone estimator
            is fitted independently.
        y : array, shape (n_samples,)
            The target values.

        Returns
        -------
        y_pred : array, shape (n_samples, n_estimators)
            Predicted values for each estimator.
        """
        return self.fit(X, y).transform(X)

    def fit(self, X, y):
        """Fit a series of independent estimators to the dataset.

        Parameters
        ----------
        X : array, shape (n_samples, n_features, n_estimators)
            The training input samples. For each data slice, a clone estimator
            is fitted independently.
        y : array, shape (n_samples,)
            The target values.

        Returns
        -------
        self : object
            Return self.
        """
        self._check_Xy(X, y)
        self.estimators_ = list()
        # For fitting, the parallelization is across estimators.
        parallel, p_func, n_jobs = parallel_func(_sl_fit, self.n_jobs)
        estimators = parallel(
            p_func(self.base_estimator, split, y)
            for split in np.array_split(X, n_jobs, axis=-1))
        self.estimators_ = np.concatenate(estimators, 0)
        return self

    def _transform(self, X, method):
        """Aux. function to make parallel predictions/transformation."""
        self._check_Xy(X)
        method = _check_method(self.base_estimator, method)
        if X.shape[-1] != len(self.estimators_):
            raise ValueError('The number of estimators does not match '
                             'X.shape[2]')
        # For predictions/transforms the parallelization is across the data and
        # not across the estimators to avoid memory load.
        parallel, p_func, n_jobs = parallel_func(_sl_transform, self.n_jobs)
        X_splits = np.array_split(X, n_jobs, axis=-1)
        est_splits = np.array_split(self.estimators_, n_jobs)
        y_pred = parallel(p_func(est, x, method)
                          for (est, x) in zip(est_splits, X_splits))

        if n_jobs > 1:
            y_pred = np.concatenate(y_pred, axis=1)
        else:
            y_pred = y_pred[0]
        return y_pred

    def transform(self, X):
        """Transform each data slice with a series of independent estimators.

        Parameters
        ----------
        X : array, shape (n_samples, n_features, n_estimators)
            The input samples. For each data slice, the corresponding estimator
            makes a transformation of the data:
            e.g. [estimators[ii].transform(X[..., ii])
                  for ii in range(n_estimators)]

        Returns
        -------
        Xt : array, shape (n_samples, n_estimators)
            Transformed values generated by each estimator.
        """
        return self._transform(X, 'transform')

    def predict(self, X):
        """Predict each data slice with a series of independent estimators.

        Parameters
        ----------
        X : array, shape (n_samples, n_features, n_estimators)
            The input samples. For each data slice, the corresponding estimator
            makes the sample predictions:
            e.g. [estimators[ii].predict(X[..., ii])
                  for ii in range(n_estimators)]

        Returns
        -------
        y_pred : array, shape (n_samples, n_estimators)
            Predicted values for each estimator/data slice.
        """
        return self._transform(X, 'predict')

    def predict_proba(self, X):
        """Predict each data slice with a series of independent estimators.

        Parameters
        ----------
        X : array, shape (n_samples, n_features, n_estimators)
            The input samples. For each data slice, the corresponding estimator
            makes the sample probabilistic predictions:
            e.g. [estimators[ii].predict_proba(X[..., ii])
                  for ii in range(n_estimators)]

        Returns
        -------
        y_pred : array, shape (n_samples, n_estimators, n_categories)
            Predicted probabilities for each estimator/data slice.
        """
        return self._transform(X, 'predict_proba')

    def decision_function(self, X):
        """Estimate distances of each data slice to the hyperplanes.

        Parameters
        ----------
        X : array, shape (n_samples, n_features, n_estimators)
            The input samples. For each data slice, the corresponding estimator
            outputs the distance to the hyperplane:
            e.g. [estimators[ii].decision_function(X[..., ii])
                  for ii in range(n_estimators)]

        Returns
        -------
        y_pred : array, shape (n_samples, n_estimators, n_classes * (n_classes-1) / 2)  # noqa
            Predicted distances for each estimator/data slice.

        Notes
        -----
        This requires base_estimator to have a `decision_function` method.
        """
        return self._transform(X, 'decision_function')

    def _check_Xy(self, X, y=None):
        """Aux. function to check input data."""
        if y is not None:
            if len(X) != len(y) or len(y) < 1:
                raise ValueError('X and y must have the same length.')
        if X.ndim != 3:
            raise ValueError('X must have at least 3 dimensions.')

    def score(self, X, y):
        """Returns the score obtained for each estimators/data slice couple.

        Parameters
        ----------
        X : array, shape (n_samples, n_features, n_estimators)
            The input samples. For each data slice, the corresponding estimator
            score the prediction: e.g. [estimators[ii].score(X[..., ii], y)
                                        for ii in range(n_estimators)]
        y : array, shape (n_samples,)
            The target values.

        Returns
        -------
        score : array, shape (n_samples, n_estimators, n_score_dim)  # noqa
            Score for each estimator / data slice couple.
        """
        self._check_Xy(X)
        if X.shape[-1] != len(self.estimators_):
            raise ValueError('The number of estimators does not match '
                             'X.shape[2]')
        # For predictions/transforms the parallelization is across the data and
        # not across the estimators to avoid memory load.
        parallel, p_func, n_jobs = parallel_func(_sl_score, self.n_jobs)
        X_splits = np.array_split(X, n_jobs, axis=-1)
        est_splits = np.array_split(self.estimators_, n_jobs)
        score = parallel(p_func(est, x, y)
                         for (est, x) in zip(est_splits, X_splits))

        if n_jobs > 1:
            score = np.concatenate(score, axis=0)
        else:
            score = score[0]
        return score


def _sl_fit(estimator, X, y):
    """Aux. function to fit SearchLight in parallel."""
    from sklearn.base import clone
    estimators_ = list()
    for ii in range(X.shape[-1]):
        est = clone(estimator)
        est.fit(X[..., ii], y)
        estimators_.append(est)
    return estimators_


def _sl_transform(estimators, X, method):
    """Aux. function to transform SearchLight in parallel."""
    n_sample, n_chan, n_iter = X.shape
    for ii, est in enumerate(estimators):
        transform = getattr(est, method)
        _y_pred = transform(X[..., ii])
        # init predictions
        if ii == 0:
            y_pred = _sl_init_pred(_y_pred, X)
        y_pred[:, ii, ...] = _y_pred
    return y_pred


def _sl_init_pred(y_pred, X):
    """Aux. function to SearchLight to initialize y_pred."""
    n_sample, n_chan, n_iter = X.shape
    if y_pred.ndim > 1:
        # for estimator that generate multidimensional y_pred,
        # e.g. clf.predict_proba()
        y_pred = np.zeros(np.r_[n_sample, n_iter, y_pred.shape[1:]], int)
    else:
        # for estimator that generate unidimensional y_pred,
        # e.g. clf.predict()
        y_pred = np.zeros((n_sample, n_iter))
    return y_pred


def _sl_score(estimators, X, y):
    """Aux. function to score SearchLight in parallel"""
    n_sample, n_chan, n_iter = X.shape
    for ii, est in enumerate(estimators):
        _score = est.score(X[..., ii], y)
        # init predictions
        if ii == 0:
            score = np.zeros(np.r_[n_iter, _score.shape], int)
        score[ii, ...] = _score
    return score


def _check_method(estimator, method):
    """Checks that an estimator has the method attribute.
    If method == 'transform'  and estimator does not have 'transform', use
    'predict' instead.
    """
    if method == 'transform' and not hasattr(estimator, 'transform'):
        method = 'predict'
    if not hasattr(estimator, method):
        ValueError('base_estimator does not have `%s` method.' % method)
    return method


class GeneralizationLight(SearchLight):
    """Generalization Light

    Fit a search-light and use them to apply a systematic cross-feature
    generalization.

    Parameters
    ----------
    base_estimator : object
        The base estimator to iteratively fit on a subset of the dataset.
    n_jobs : int, optional (default=1)
        The number of jobs to run in parallel for both `fit` and `predict`.
        If -1, then the number of jobs is set to the number of cores.
    """

    def _transform(self, X, method):
        """Aux. function to make parallel predictions/transformation"""
        self._check_Xy(X)
        method = _check_method(self.base_estimator, method)
        parallel, p_func, n_jobs = parallel_func(_gl_transform, self.n_jobs)
        y_pred = parallel(
            p_func(self.estimators_, x_split, method)
            for x_split in np.array_split(X, n_jobs, axis=2))

        y_pred = np.concatenate(y_pred, axis=2)
        return y_pred

    def transform(self, X):
        """Transform each data slice with all possible estimators.

        Parameters
        ----------
        X : array, shape (n_samples, n_features, n_estimators)
            The input samples. For estimator the corresponding data slice is
            used to make a transformation.

        Returns
        -------
        Xt : array, shape (n_samples, n_estimators, n_slices)
            Transformed values generated by each estimator.
        """
        return self._transform(X, 'transform')

    def predict(self, X):
        """Predict each data slice with all possible estimators.

        Parameters
        ----------
        X : array, shape (n_samples, n_features, n_estimators)
            The training input samples. For each data slice, a clone estimator
            is fitted independently.

        Returns
        -------
        y_pred : array, shape (n_samples, n_estimators, n_slices)
            Predicted values for each estimator.
        """
        return self._transform(X, 'predict')

    def predict_proba(self, X):
        """Estimate probabilistic estimates of each data slice with all
        possible estimators.

        Parameters
        ----------
        X : array, shape (n_samples, n_features, n_estimators)
            The training input samples. For each data slice, a clone estimator
            is fitted independently.

        Returns
        -------
        y_pred : array, shape (n_samples, n_estimators, n_slices, n_classes)
            Predicted values for each estimator.

        Notes
        -----
        This requires base_estimator to have a `predict_proba` method.
        """
        return self._transform(X, 'predict_proba')

    def decision_function(self, X):
        """Estimate distances of each data slice to all hyperplanes.

        Parameters
        ----------
        X : array, shape (n_samples, n_features, n_estimators)
            The training input samples. Each estimator output the distance to
            its hyperplane: e.g. [estimators[ii].decision_function(X[..., ii])
                                  for ii in range(n_estimators)]

        Returns
        -------
        y_pred : array, shape (n_samples, n_estimators, n_slices, n_classes)
            Predicted values for each estimator.

        Notes
        -----
        This requires base_estimator to have a `decision_function` method.
        """
        return self._transform(X, 'decision_function')

    def score(self, X, y):
        """Returns the score obtained for each combination of estimators and
        tested dimensions.

        Parameters
        ----------
        X : array, shape (n_samples, n_features, n_estimators)
            The input samples. For each data slice, the corresponding estimator
            score the prediction:
            e.g. [estimators[ii].score(X[..., ii], y)
                  for ii in range(n_estimators)]
        y : array, shape (n_samples,)
            The target values.

        Returns
        -------
        score : array, shape (n_samples, n_estimators, n_slices, n_score_dim)  # noqa
            Score for each estimator / data slice couple.

        Notes
        -----
        This requires base_estimator to have a `decision_function` method.
        """
        self._check_Xy(X)
        # For predictions/transforms the parallelization is across the data and
        # not across the estimators to avoid memory load.
        parallel, p_func, n_jobs = parallel_func(_gl_score, self.n_jobs)
        X_splits = np.array_split(X, n_jobs, axis=-1)
        score = parallel(p_func(self.estimators_, x, y) for x in X_splits)

        if n_jobs > 1:
            score = np.concatenate(score, axis=1)
        else:
            score = score[0]
        return score


def _gl_transform(estimators, X, method):
    """Transform the dataset by applying each estimator to all slices of
    the data.

    Parameters
    ----------
    X : array, shape (n_samples, n_features, n_estimators)
        The training input samples. For each data slice, a clone estimator
        is fitted independently.

    Returns
    -------
    Xt : array, shape (n_samples, n_estimators)
        Transformed values generated by each estimator.
    """
    n_sample, n_chan, n_iter = X.shape
    for ii, est in enumerate(estimators):
        # stack generalized data for faster prediction
        X_stack = np.transpose(X, [1, 0, 2])
        X_stack = np.reshape(X_stack, [n_chan, n_sample * n_iter]).T
        transform = getattr(est, method)
        _y_pred = transform(X_stack)
        # unstack generalizations
        if _y_pred.ndim == 2:
            _y_pred = np.reshape(_y_pred, [n_sample, n_iter, _y_pred.shape[1]])
        else:
            shape = np.r_[n_sample, n_iter, _y_pred.shape[1:]].astype(int)
            _y_pred = np.reshape(_y_pred, shape)
        # init
        if ii == 0:
            y_pred = _gl_init_pred(_y_pred, X, len(estimators))
        y_pred[:, ii, ...] = _y_pred
    return y_pred


def _gl_init_pred(y_pred, X, n_train):
    """Aux. function to GeneralizationLight to initialize y_pred"""
    n_sample, n_chan, n_iter = X.shape
    if y_pred.ndim == 3:
        y_pred = np.zeros((n_sample, n_train, n_iter, y_pred.shape[-1]))
    else:
        y_pred = np.zeros((n_sample, n_train, n_iter))
    return y_pred


def _gl_score(estimators, X, y):
    """Aux. function to score GeneralizationLight in parallel"""
    # FIXME: The parallization is a bit high, it might be memory consuming.
    n_sample, n_chan, n_iter = X.shape
    n_est = len(estimators)
    for ii, est in enumerate(estimators):
        for jj in range(X.shape[-1]):
            _score = est.score(X[..., jj], y)
            # init predictions
            if (ii == 0) & (jj == 0):
                if np.ndim(_score):
                    score = np.zeros(np.r_[n_est, n_iter, _score.shape], int)
                else:
                    score = np.zeros([n_est, n_iter])
            score[ii, jj, ...] = _score
    return score
