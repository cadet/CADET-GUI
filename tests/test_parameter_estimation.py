from __future__ import annotations

from cadetgui.widgets.composite import DataImportWidget, ParameterEstimationWidget


def test_parameter_estimation_widget_nests_a_data_import_widget():
    pw = ParameterEstimationWidget()

    assert isinstance(pw.data, DataImportWidget)
    assert pw.data.root in pw.root.children


def test_parameter_estimation_widget_accepts_a_prebuilt_data_widget():
    dw = DataImportWidget()
    pw = ParameterEstimationWidget(data=dw)

    assert pw.data is dw
