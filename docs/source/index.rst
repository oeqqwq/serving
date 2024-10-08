.. SecretFlow-Serving documentation master file, created by
   sphinx-quickstart on Sat Oct  7 17:42:31 2023.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to SecretFlow-Serving's documentation!
==============================================

SecretFlow-Serving is a serving system for privacy-preserving machine learning models.


Getting started
---------------

Follow the :doc:`tutorial </intro/tutorial>` and try out SecretFlow-Serving on your machine!


SecretFlow-Serving Systems
--------------------------

- **Overview**:
  :doc:`System overview and architecture </topics/system/intro>`

- **Observability**:
  :doc:`Logs, Metrics and Trace </topics/system/observability>`

- **FeatureSource**:
  :doc:`Feature Service </topics/system/feature_service>`

Deployment
----------

- **Guides**:
  :doc:`How to deploy an SecretFlow-Serving cluster </topics/deployment/deployment>` |
  :doc:`Serving on Kuscia </topics/deployment/serving_on_kuscia>`

- **Reference**:
  :doc:`SecretFlow-Serving service API </reference/api>` |
  :doc:`SecretFlow-Serving system config </reference/config>` |
  :doc:`SecretFlow-Serving feature service spi </reference/spi>`


Graph
-----------------

- **Overview**:
  :doc:`Introduction to graphs </topics/graph/intro_to_graph>` |
  :doc:`Operators </topics/graph/operator_list>`

- **Reference**:
  :doc:`SecretFlow-Serving model </reference/model>` |
  :doc:`secretflow-serving-lib docs </reference/modules>`

Prediction Algorithms
---------------------

- **Introduction**:
  :doc:`Introduction to prediction algorithms </topics/algorithm/intro>`

.. toctree::
    :hidden:

    intro/index
    topics/index
    reference/index
