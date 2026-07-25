// GENERATED FILE — DO NOT EDIT.
//
// Source of truth: knowledge/spine/*.json
// Regenerate:      node knowledge/spine-render.mjs
// CI gate:         node knowledge/spine-render.mjs --check
//
// The seed spine is DATA (knowledge/spine), not code. This module exists so the
// app and the server keep importing a TypeScript symbol, and so neither build
// needs resolveJsonModule; it carries no information the JSON does not.
import { TaxonomyData } from '../types/taxonomy';

export const taxonomyData: TaxonomyData = {
  "01_natural_sciences": {
    "name": "Natural Sciences",
    "id": "01",
    "description": "Study of natural phenomena",
    "subcategories": {
      "01_physics": {
        "name": "Physics",
        "id": "01.01",
        "subcategories": {
          "01_classical_mechanics": {
            "name": "Classical Mechanics",
            "id": "01.01.01",
            "subcategories": {
              "01_kinematics": {
                "name": "Kinematics",
                "id": "01.01.01.01",
                "items": [
                  {
                    "id": "01.01.01.01.01",
                    "name": "Motion equations"
                  },
                  {
                    "id": "01.01.01.01.02",
                    "name": "Projectile motion"
                  },
                  {
                    "id": "01.01.01.01.03",
                    "name": "Circular motion"
                  },
                  {
                    "id": "01.01.01.01.04",
                    "name": "Relative motion"
                  },
                  {
                    "id": "01.01.01.01.05",
                    "name": "Reference frames"
                  }
                ]
              },
              "02_dynamics": {
                "name": "Dynamics",
                "id": "01.01.01.02",
                "items": [
                  {
                    "id": "01.01.01.02.01",
                    "name": "Newton's laws"
                  },
                  {
                    "id": "01.01.01.02.02",
                    "name": "Forces and interactions"
                  },
                  {
                    "id": "01.01.01.02.03",
                    "name": "Work and energy"
                  },
                  {
                    "id": "01.01.01.02.04",
                    "name": "Momentum"
                  },
                  {
                    "id": "01.01.01.02.05",
                    "name": "Collisions"
                  }
                ]
              },
              "03_statics": {
                "name": "Statics",
                "id": "01.01.01.03"
              },
              "04_fluid_mechanics": {
                "name": "Fluid Mechanics",
                "id": "01.01.01.04"
              },
              "05_oscillations_waves": {
                "name": "Oscillations & Waves",
                "id": "01.01.01.05"
              }
            }
          },
          "02_quantum_mechanics": {
            "name": "Quantum Mechanics",
            "id": "01.01.02",
            "subcategories": {
              "01_foundations": {
                "name": "Quantum Foundations",
                "id": "01.01.02.01"
              },
              "02_quantum_field_theory": {
                "name": "Quantum Field Theory",
                "id": "01.01.02.02"
              },
              "03_quantum_computing": {
                "name": "Quantum Computing",
                "id": "01.01.02.03"
              },
              "04_quantum_optics": {
                "name": "Quantum Optics",
                "id": "01.01.02.04"
              }
            }
          },
          "03_thermodynamics": {
            "name": "Thermodynamics",
            "id": "01.01.03"
          },
          "04_electromagnetism": {
            "name": "Electromagnetism",
            "id": "01.01.04"
          },
          "05_relativity": {
            "name": "Relativity",
            "id": "01.01.05"
          },
          "06_nuclear_physics": {
            "name": "Nuclear Physics",
            "id": "01.01.06"
          },
          "07_particle_physics": {
            "name": "Particle Physics",
            "id": "01.01.07"
          },
          "08_astrophysics": {
            "name": "Astrophysics",
            "id": "01.01.08"
          },
          "09_geophysics": {
            "name": "Geophysics",
            "id": "01.01.09"
          },
          "10_biophysics": {
            "name": "Biophysics",
            "id": "01.01.10"
          }
        }
      },
      "02_chemistry": {
        "name": "Chemistry",
        "id": "01.02",
        "subcategories": {
          "01_general_chemistry": {
            "name": "General Chemistry",
            "id": "01.02.01"
          },
          "02_organic_chemistry": {
            "name": "Organic Chemistry",
            "id": "01.02.02"
          },
          "03_inorganic_chemistry": {
            "name": "Inorganic Chemistry",
            "id": "01.02.03"
          },
          "04_physical_chemistry": {
            "name": "Physical Chemistry",
            "id": "01.02.04"
          },
          "05_analytical_chemistry": {
            "name": "Analytical Chemistry",
            "id": "01.02.05"
          },
          "06_biochemistry": {
            "name": "Biochemistry",
            "id": "01.02.06"
          },
          "07_environmental_chemistry": {
            "name": "Environmental Chemistry",
            "id": "01.02.07"
          },
          "08_medicinal_chemistry": {
            "name": "Medicinal Chemistry",
            "id": "01.02.08"
          },
          "09_materials_chemistry": {
            "name": "Materials Chemistry",
            "id": "01.02.09"
          },
          "10_computational_chemistry": {
            "name": "Computational Chemistry",
            "id": "01.02.10"
          }
        }
      },
      "03_biology": {
        "name": "Biology",
        "id": "01.03",
        "subcategories": {
          "01_molecular_biology": {
            "name": "Molecular Biology",
            "id": "01.03.01"
          },
          "02_cell_biology": {
            "name": "Cell Biology",
            "id": "01.03.02"
          },
          "03_genetics": {
            "name": "Genetics",
            "id": "01.03.03"
          },
          "04_evolutionary_biology": {
            "name": "Evolutionary Biology",
            "id": "01.03.04"
          },
          "05_ecology": {
            "name": "Ecology",
            "id": "01.03.05"
          },
          "06_zoology": {
            "name": "Zoology",
            "id": "01.03.06"
          },
          "07_botany": {
            "name": "Botany",
            "id": "01.03.07"
          },
          "08_microbiology": {
            "name": "Microbiology",
            "id": "01.03.08"
          },
          "09_marine_biology": {
            "name": "Marine Biology",
            "id": "01.03.09"
          },
          "10_neurobiology": {
            "name": "Neurobiology",
            "id": "01.03.10"
          }
        }
      },
      "04_earth_sciences": {
        "name": "Earth Sciences",
        "id": "01.04",
        "subcategories": {
          "01_geology": {
            "name": "Geology",
            "id": "01.04.01"
          },
          "02_meteorology": {
            "name": "Meteorology",
            "id": "01.04.02"
          },
          "03_oceanography": {
            "name": "Oceanography",
            "id": "01.04.03"
          },
          "04_climatology": {
            "name": "Climatology",
            "id": "01.04.04"
          },
          "05_paleontology": {
            "name": "Paleontology",
            "id": "01.04.05"
          },
          "06_mineralogy": {
            "name": "Mineralogy",
            "id": "01.04.06"
          },
          "07_volcanology": {
            "name": "Volcanology",
            "id": "01.04.07"
          },
          "08_seismology": {
            "name": "Seismology",
            "id": "01.04.08"
          },
          "09_hydrology": {
            "name": "Hydrology",
            "id": "01.04.09"
          },
          "10_glaciology": {
            "name": "Glaciology",
            "id": "01.04.10"
          }
        }
      },
      "05_astronomy": {
        "name": "Astronomy",
        "id": "01.05",
        "subcategories": {
          "01_planetary_science": {
            "name": "Planetary Science",
            "id": "01.05.01"
          },
          "02_stellar_astronomy": {
            "name": "Stellar Astronomy",
            "id": "01.05.02"
          },
          "03_galactic_astronomy": {
            "name": "Galactic Astronomy",
            "id": "01.05.03"
          },
          "04_cosmology": {
            "name": "Cosmology",
            "id": "01.05.04"
          },
          "05_astrobiology": {
            "name": "Astrobiology",
            "id": "01.05.05"
          }
        }
      }
    }
  },
  "02_formal_sciences": {
    "name": "Formal Sciences",
    "id": "02",
    "description": "Abstract structures and logic",
    "subcategories": {
      "01_mathematics": {
        "name": "Mathematics",
        "id": "02.01",
        "subcategories": {
          "01_pure_mathematics": {
            "name": "Pure Mathematics",
            "id": "02.01.01",
            "subcategories": {
              "01_algebra": {
                "name": "Algebra",
                "id": "02.01.01.01",
                "subcategories": {
                  "01_elementary": {
                    "name": "Elementary Algebra",
                    "id": "02.01.01.01.01",
                    "items": [
                      {
                        "id": "02.01.01.01.01.01",
                        "name": "Linear equations"
                      },
                      {
                        "id": "02.01.01.01.01.02",
                        "name": "Quadratic equations"
                      },
                      {
                        "id": "02.01.01.01.01.03",
                        "name": "Polynomials"
                      },
                      {
                        "id": "02.01.01.01.01.04",
                        "name": "Factorization"
                      },
                      {
                        "id": "02.01.01.01.01.05",
                        "name": "Systems of equations"
                      }
                    ]
                  },
                  "02_linear": {
                    "name": "Linear Algebra",
                    "id": "02.01.01.01.02",
                    "items": [
                      {
                        "id": "02.01.01.01.02.01",
                        "name": "Matrices"
                      },
                      {
                        "id": "02.01.01.01.02.02",
                        "name": "Vector spaces"
                      },
                      {
                        "id": "02.01.01.01.02.03",
                        "name": "Eigenvalues"
                      },
                      {
                        "id": "02.01.01.01.02.04",
                        "name": "Linear transformations"
                      },
                      {
                        "id": "02.01.01.01.02.05",
                        "name": "Determinants"
                      }
                    ]
                  },
                  "03_abstract": {
                    "name": "Abstract Algebra",
                    "id": "02.01.01.01.03"
                  },
                  "04_commutative": {
                    "name": "Commutative Algebra",
                    "id": "02.01.01.01.04"
                  },
                  "05_homological": {
                    "name": "Homological Algebra",
                    "id": "02.01.01.01.05"
                  }
                }
              },
              "02_analysis": {
                "name": "Analysis",
                "id": "02.01.01.02",
                "subcategories": {
                  "01_real": {
                    "name": "Real Analysis",
                    "id": "02.01.01.02.01"
                  },
                  "02_complex": {
                    "name": "Complex Analysis",
                    "id": "02.01.01.02.02"
                  },
                  "03_functional": {
                    "name": "Functional Analysis",
                    "id": "02.01.01.02.03"
                  },
                  "04_harmonic": {
                    "name": "Harmonic Analysis",
                    "id": "02.01.01.02.04"
                  },
                  "05_measure": {
                    "name": "Measure Theory",
                    "id": "02.01.01.02.05"
                  }
                }
              },
              "03_geometry": {
                "name": "Geometry",
                "id": "02.01.01.03",
                "subcategories": {
                  "01_euclidean": {
                    "name": "Euclidean Geometry",
                    "id": "02.01.01.03.01"
                  },
                  "02_differential": {
                    "name": "Differential Geometry",
                    "id": "02.01.01.03.02"
                  },
                  "03_algebraic": {
                    "name": "Algebraic Geometry",
                    "id": "02.01.01.03.03"
                  },
                  "04_riemannian": {
                    "name": "Riemannian Geometry",
                    "id": "02.01.01.03.04"
                  },
                  "05_symplectic": {
                    "name": "Symplectic Geometry",
                    "id": "02.01.01.03.05"
                  }
                }
              },
              "04_topology": {
                "name": "Topology",
                "id": "02.01.01.04"
              },
              "05_number_theory": {
                "name": "Number Theory",
                "id": "02.01.01.05"
              }
            }
          },
          "02_applied_mathematics": {
            "name": "Applied Mathematics",
            "id": "02.01.02",
            "subcategories": {
              "01_statistics": {
                "name": "Statistics",
                "id": "02.01.02.01",
                "subcategories": {
                  "01_descriptive": {
                    "name": "Descriptive Statistics",
                    "id": "02.01.02.01.01"
                  },
                  "02_inferential": {
                    "name": "Inferential Statistics",
                    "id": "02.01.02.01.02"
                  },
                  "03_bayesian": {
                    "name": "Bayesian Statistics",
                    "id": "02.01.02.01.03"
                  },
                  "04_time_series": {
                    "name": "Time Series Analysis",
                    "id": "02.01.02.01.04"
                  },
                  "05_multivariate": {
                    "name": "Multivariate Analysis",
                    "id": "02.01.02.01.05"
                  }
                }
              },
              "02_probability": {
                "name": "Probability",
                "id": "02.01.02.02"
              },
              "03_numerical_analysis": {
                "name": "Numerical Analysis",
                "id": "02.01.02.03"
              },
              "04_optimization": {
                "name": "Optimization",
                "id": "02.01.02.04"
              },
              "05_game_theory": {
                "name": "Game Theory",
                "id": "02.01.02.05"
              }
            }
          },
          "03_computational_mathematics": {
            "name": "Computational Mathematics",
            "id": "02.01.03"
          }
        }
      },
      "02_computer_science": {
        "name": "Computer Science",
        "id": "02.02",
        "subcategories": {
          "01_theoretical_cs": {
            "name": "Theoretical Computer Science",
            "id": "02.02.01",
            "subcategories": {
              "01_automata_theory": {
                "name": "Automata Theory",
                "id": "02.02.01.01",
                "items": [
                  {
                    "id": "02.02.01.01.01",
                    "name": "Finite automata"
                  },
                  {
                    "id": "02.02.01.01.02",
                    "name": "Pushdown automata"
                  },
                  {
                    "id": "02.02.01.01.03",
                    "name": "Turing machines"
                  },
                  {
                    "id": "02.02.01.01.04",
                    "name": "Regular expressions"
                  },
                  {
                    "id": "02.02.01.01.05",
                    "name": "Context-free grammars"
                  }
                ]
              },
              "02_complexity_theory": {
                "name": "Complexity Theory",
                "id": "02.02.01.02",
                "items": [
                  {
                    "id": "02.02.01.02.01",
                    "name": "P vs NP"
                  },
                  {
                    "id": "02.02.01.02.02",
                    "name": "Complexity classes"
                  },
                  {
                    "id": "02.02.01.02.03",
                    "name": "Reduction techniques"
                  }
                ]
              },
              "03_formal_methods": {
                "name": "Formal Methods",
                "id": "02.02.01.03"
              },
              "04_type_theory": {
                "name": "Type Theory",
                "id": "02.02.01.04"
              },
              "05_lambda_calculus": {
                "name": "Lambda Calculus",
                "id": "02.02.01.05"
              }
            }
          },
          "02_algorithms_data_structures": {
            "name": "Algorithms & Data Structures",
            "id": "02.02.02",
            "subcategories": {
              "01_sorting_algorithms": {
                "name": "Sorting Algorithms",
                "id": "02.02.02.01",
                "items": [
                  {
                    "id": "02.02.02.01.01",
                    "name": "Quicksort"
                  },
                  {
                    "id": "02.02.02.01.02",
                    "name": "Mergesort"
                  },
                  {
                    "id": "02.02.02.01.03",
                    "name": "Heapsort"
                  },
                  {
                    "id": "02.02.02.01.04",
                    "name": "Radix sort"
                  },
                  {
                    "id": "02.02.02.01.05",
                    "name": "Timsort"
                  }
                ]
              },
              "02_search_algorithms": {
                "name": "Search Algorithms",
                "id": "02.02.02.02"
              },
              "03_graph_algorithms": {
                "name": "Graph Algorithms",
                "id": "02.02.02.03"
              },
              "04_dynamic_programming": {
                "name": "Dynamic Programming",
                "id": "02.02.02.04"
              },
              "05_data_structures": {
                "name": "Data Structures",
                "id": "02.02.02.05",
                "items": [
                  {
                    "id": "02.02.02.05.01",
                    "name": "Trees (BST, AVL, B-trees)"
                  },
                  {
                    "id": "02.02.02.05.02",
                    "name": "Hash tables"
                  },
                  {
                    "id": "02.02.02.05.03",
                    "name": "Heaps"
                  },
                  {
                    "id": "02.02.02.05.04",
                    "name": "Graphs"
                  },
                  {
                    "id": "02.02.02.05.05",
                    "name": "Tries"
                  }
                ]
              }
            }
          },
          "03_programming_languages": {
            "name": "Programming Languages",
            "id": "02.02.03",
            "subcategories": {
              "01_system_languages": {
                "name": "System Languages",
                "id": "02.02.03.01",
                "items": [
                  {
                    "id": "02.02.03.01.01",
                    "name": "C"
                  },
                  {
                    "id": "02.02.03.01.02",
                    "name": "C++"
                  },
                  {
                    "id": "02.02.03.01.03",
                    "name": "Rust"
                  },
                  {
                    "id": "02.02.03.01.04",
                    "name": "Go"
                  },
                  {
                    "id": "02.02.03.01.05",
                    "name": "Assembly"
                  }
                ]
              },
              "02_scripting_languages": {
                "name": "Scripting Languages",
                "id": "02.02.03.02",
                "items": [
                  {
                    "id": "02.02.03.02.01",
                    "name": "Python"
                  },
                  {
                    "id": "02.02.03.02.02",
                    "name": "JavaScript"
                  },
                  {
                    "id": "02.02.03.02.03",
                    "name": "Ruby"
                  },
                  {
                    "id": "02.02.03.02.04",
                    "name": "Perl"
                  },
                  {
                    "id": "02.02.03.02.05",
                    "name": "PHP"
                  }
                ]
              },
              "03_functional_languages": {
                "name": "Functional Languages",
                "id": "02.02.03.03"
              },
              "04_jvm_languages": {
                "name": "JVM Languages",
                "id": "02.02.03.04"
              },
              "05_domain_specific": {
                "name": "Domain Specific Languages",
                "id": "02.02.03.05"
              }
            }
          },
          "04_software_engineering": {
            "name": "Software Engineering",
            "id": "02.02.04",
            "subcategories": {
              "01_design_patterns": {
                "name": "Design Patterns",
                "id": "02.02.04.01"
              },
              "02_architecture": {
                "name": "Software Architecture",
                "id": "02.02.04.02"
              },
              "03_testing": {
                "name": "Testing",
                "id": "02.02.04.03"
              },
              "04_devops": {
                "name": "DevOps",
                "id": "02.02.04.04"
              },
              "05_agile_methods": {
                "name": "Agile Methodologies",
                "id": "02.02.04.05"
              }
            }
          },
          "05_databases": {
            "name": "Databases",
            "id": "02.02.05",
            "subcategories": {
              "01_relational": {
                "name": "Relational Databases",
                "id": "02.02.05.01"
              },
              "02_nosql": {
                "name": "NoSQL Databases",
                "id": "02.02.05.02"
              },
              "03_database_theory": {
                "name": "Database Theory",
                "id": "02.02.05.03"
              },
              "04_sql": {
                "name": "SQL",
                "id": "02.02.05.04"
              },
              "05_data_warehousing": {
                "name": "Data Warehousing",
                "id": "02.02.05.05"
              }
            }
          },
          "06_operating_systems": {
            "name": "Operating Systems",
            "id": "02.02.06",
            "subcategories": {
              "01_kernel_design": {
                "name": "Kernel Design",
                "id": "02.02.06.01"
              },
              "02_process_management": {
                "name": "Process Management",
                "id": "02.02.06.02"
              },
              "03_memory_management": {
                "name": "Memory Management",
                "id": "02.02.06.03"
              },
              "04_file_systems": {
                "name": "File Systems",
                "id": "02.02.06.04"
              },
              "05_device_drivers": {
                "name": "Device Drivers",
                "id": "02.02.06.05"
              }
            }
          },
          "07_networks": {
            "name": "Computer Networks",
            "id": "02.02.07",
            "subcategories": {
              "01_protocols": {
                "name": "Network Protocols",
                "id": "02.02.07.01"
              },
              "02_network_security": {
                "name": "Network Security",
                "id": "02.02.07.02"
              },
              "03_distributed_systems": {
                "name": "Distributed Systems",
                "id": "02.02.07.03"
              },
              "04_web_technologies": {
                "name": "Web Technologies",
                "id": "02.02.07.04"
              },
              "05_wireless_networks": {
                "name": "Wireless Networks",
                "id": "02.02.07.05"
              }
            }
          },
          "08_security": {
            "name": "Computer Security",
            "id": "02.02.08",
            "subcategories": {
              "01_cryptography": {
                "name": "Cryptography",
                "id": "02.02.08.01"
              },
              "02_network_security": {
                "name": "Network Security",
                "id": "02.02.08.02"
              },
              "03_application_security": {
                "name": "Application Security",
                "id": "02.02.08.03"
              },
              "04_malware_analysis": {
                "name": "Malware Analysis",
                "id": "02.02.08.04"
              },
              "05_forensics": {
                "name": "Digital Forensics",
                "id": "02.02.08.05"
              }
            }
          },
          "09_artificial_intelligence": {
            "name": "Artificial Intelligence",
            "id": "02.02.09",
            "subcategories": {
              "01_machine_learning": {
                "name": "Machine Learning",
                "id": "02.02.09.01"
              },
              "02_deep_learning": {
                "name": "Deep Learning",
                "id": "02.02.09.02"
              },
              "03_nlp": {
                "name": "Natural Language Processing",
                "id": "02.02.09.03"
              },
              "04_computer_vision": {
                "name": "Computer Vision",
                "id": "02.02.09.04"
              },
              "05_reinforcement_learning": {
                "name": "Reinforcement Learning",
                "id": "02.02.09.05"
              }
            }
          },
          "10_computer_graphics": {
            "name": "Computer Graphics",
            "id": "02.02.10"
          }
        }
      },
      "03_logic": {
        "name": "Logic",
        "id": "02.03",
        "subcategories": {
          "01_mathematical_logic": {
            "name": "Mathematical Logic",
            "id": "02.03.01"
          },
          "02_philosophical_logic": {
            "name": "Philosophical Logic",
            "id": "02.03.02"
          },
          "03_computational_logic": {
            "name": "Computational Logic",
            "id": "02.03.03"
          }
        }
      },
      "04_information_theory": {
        "name": "Information Theory",
        "id": "02.04"
      },
      "05_systems_theory": {
        "name": "Systems Theory",
        "id": "02.05"
      }
    }
  },
  "03_applied_sciences": {
    "name": "Applied Sciences & Technology",
    "id": "03",
    "description": "Practical applications of knowledge",
    "subcategories": {
      "01_engineering": {
        "name": "Engineering",
        "id": "03.01",
        "subcategories": {
          "01_civil_engineering": {
            "name": "Civil Engineering",
            "id": "03.01.01",
            "subcategories": {
              "01_structural": {
                "name": "Structural Engineering",
                "id": "03.01.01.01",
                "subcategories": {
                  "01_load_analysis": {
                    "name": "Load Analysis",
                    "id": "03.01.01.01.01",
                    "items": [
                      {
                        "id": "03.01.01.01.01.01",
                        "name": "Dead loads"
                      },
                      {
                        "id": "03.01.01.01.01.02",
                        "name": "Live loads"
                      },
                      {
                        "id": "03.01.01.01.01.03",
                        "name": "Wind loads"
                      },
                      {
                        "id": "03.01.01.01.01.04",
                        "name": "Seismic loads"
                      },
                      {
                        "id": "03.01.01.01.01.05",
                        "name": "Load combinations"
                      }
                    ]
                  },
                  "02_materials": {
                    "name": "Construction Materials",
                    "id": "03.01.01.01.02"
                  },
                  "03_foundations": {
                    "name": "Foundation Design",
                    "id": "03.01.01.01.03"
                  },
                  "04_bridges": {
                    "name": "Bridge Engineering",
                    "id": "03.01.01.01.04"
                  },
                  "05_tall_buildings": {
                    "name": "High-rise Design",
                    "id": "03.01.01.01.05"
                  }
                }
              },
              "02_transportation": {
                "name": "Transportation Engineering",
                "id": "03.01.01.02",
                "subcategories": {
                  "01_roads": {
                    "name": "Road Design",
                    "id": "03.01.01.02.01"
                  },
                  "02_railways": {
                    "name": "Railway Engineering",
                    "id": "03.01.01.02.02"
                  },
                  "03_airports": {
                    "name": "Airport Design",
                    "id": "03.01.01.02.03"
                  },
                  "04_traffic": {
                    "name": "Traffic Engineering",
                    "id": "03.01.01.02.04"
                  },
                  "05_pavements": {
                    "name": "Pavement Design",
                    "id": "03.01.01.02.05"
                  }
                }
              },
              "03_water_resources": {
                "name": "Water Resources",
                "id": "03.01.01.03"
              },
              "04_geotechnical": {
                "name": "Geotechnical Engineering",
                "id": "03.01.01.04"
              },
              "05_environmental": {
                "name": "Environmental Engineering",
                "id": "03.01.01.05"
              }
            }
          },
          "02_mechanical_engineering": {
            "name": "Mechanical Engineering",
            "id": "03.01.02",
            "subcategories": {
              "01_thermodynamics": {
                "name": "Applied Thermodynamics",
                "id": "03.01.02.01"
              },
              "02_fluid_mechanics": {
                "name": "Fluid Mechanics",
                "id": "03.01.02.02"
              },
              "03_machine_design": {
                "name": "Machine Design",
                "id": "03.01.02.03"
              },
              "04_manufacturing": {
                "name": "Manufacturing Processes",
                "id": "03.01.02.04"
              },
              "05_robotics": {
                "name": "Robotics",
                "id": "03.01.02.05"
              }
            }
          },
          "03_electrical_engineering": {
            "name": "Electrical Engineering",
            "id": "03.01.03",
            "subcategories": {
              "01_power_systems": {
                "name": "Power Systems",
                "id": "03.01.03.01",
                "subcategories": {
                  "01_generation": {
                    "name": "Power Generation",
                    "id": "03.01.03.01.01"
                  },
                  "02_transmission": {
                    "name": "Power Transmission",
                    "id": "03.01.03.01.02"
                  },
                  "03_distribution": {
                    "name": "Power Distribution",
                    "id": "03.01.03.01.03"
                  },
                  "04_protection": {
                    "name": "System Protection",
                    "id": "03.01.03.01.04"
                  },
                  "05_smart_grids": {
                    "name": "Smart Grids",
                    "id": "03.01.03.01.05"
                  }
                }
              },
              "02_electronics": {
                "name": "Electronics Engineering",
                "id": "03.01.03.02"
              },
              "03_control_systems": {
                "name": "Control Systems",
                "id": "03.01.03.03"
              },
              "04_telecommunications": {
                "name": "Telecommunications",
                "id": "03.01.03.04"
              },
              "05_signal_processing": {
                "name": "Signal Processing",
                "id": "03.01.03.05"
              }
            }
          },
          "04_chemical_engineering": {
            "name": "Chemical Engineering",
            "id": "03.01.04",
            "subcategories": {
              "01_process_design": {
                "name": "Process Design",
                "id": "03.01.04.01"
              },
              "02_reaction_engineering": {
                "name": "Reaction Engineering",
                "id": "03.01.04.02"
              },
              "03_separation_processes": {
                "name": "Separation Processes",
                "id": "03.01.04.03"
              },
              "04_process_control": {
                "name": "Process Control",
                "id": "03.01.04.04"
              },
              "05_safety": {
                "name": "Process Safety",
                "id": "03.01.04.05"
              }
            }
          },
          "05_aerospace_engineering": {
            "name": "Aerospace Engineering",
            "id": "03.01.05"
          },
          "06_biomedical_engineering": {
            "name": "Biomedical Engineering",
            "id": "03.01.06"
          },
          "07_environmental_engineering": {
            "name": "Environmental Engineering",
            "id": "03.01.07"
          },
          "08_materials_engineering": {
            "name": "Materials Engineering",
            "id": "03.01.08"
          },
          "09_nuclear_engineering": {
            "name": "Nuclear Engineering",
            "id": "03.01.09"
          },
          "10_software_engineering": {
            "name": "Software Engineering",
            "id": "03.01.10"
          }
        }
      },
      "02_medicine": {
        "name": "Medicine",
        "id": "03.02",
        "subcategories": {
          "01_anatomy": {
            "name": "Anatomy",
            "id": "03.02.01",
            "subcategories": {
              "01_skeletal_system": {
                "name": "Skeletal System",
                "id": "03.02.01.01"
              },
              "02_muscular_system": {
                "name": "Muscular System",
                "id": "03.02.01.02"
              },
              "03_nervous_system": {
                "name": "Nervous System",
                "id": "03.02.01.03"
              },
              "04_cardiovascular": {
                "name": "Cardiovascular System",
                "id": "03.02.01.04"
              },
              "05_respiratory": {
                "name": "Respiratory System",
                "id": "03.02.01.05"
              }
            }
          },
          "02_physiology": {
            "name": "Physiology",
            "id": "03.02.02",
            "subcategories": {
              "01_cellular": {
                "name": "Cellular Physiology",
                "id": "03.02.02.01"
              },
              "02_organ_systems": {
                "name": "Organ Systems",
                "id": "03.02.02.02"
              },
              "03_homeostasis": {
                "name": "Homeostasis",
                "id": "03.02.02.03"
              },
              "04_metabolism": {
                "name": "Metabolism",
                "id": "03.02.02.04"
              },
              "05_endocrinology": {
                "name": "Endocrinology",
                "id": "03.02.02.05"
              }
            }
          },
          "03_pathology": {
            "name": "Pathology",
            "id": "03.02.03",
            "subcategories": {
              "01_infectious_diseases": {
                "name": "Infectious Diseases",
                "id": "03.02.03.01"
              },
              "02_genetic_disorders": {
                "name": "Genetic Disorders",
                "id": "03.02.03.02"
              },
              "03_cancer": {
                "name": "Oncology",
                "id": "03.02.03.03"
              },
              "04_autoimmune": {
                "name": "Autoimmune Diseases",
                "id": "03.02.03.04"
              },
              "05_degenerative": {
                "name": "Degenerative Diseases",
                "id": "03.02.03.05"
              }
            }
          },
          "04_pharmacology": {
            "name": "Pharmacology",
            "id": "03.02.04",
            "subcategories": {
              "01_antibiotics": {
                "name": "Antibiotics",
                "id": "03.02.04.01"
              },
              "02_analgesics": {
                "name": "Pain Management",
                "id": "03.02.04.02"
              },
              "03_cardiovascular_drugs": {
                "name": "Cardiovascular Drugs",
                "id": "03.02.04.03"
              },
              "04_psychotropics": {
                "name": "Psychotropic Medications",
                "id": "03.02.04.04"
              },
              "05_drug_production": {
                "name": "Pharmaceutical Production",
                "id": "03.02.04.05"
              }
            }
          },
          "05_clinical_medicine": {
            "name": "Clinical Medicine",
            "id": "03.02.05",
            "subcategories": {
              "01_diagnosis": {
                "name": "Diagnostic Methods",
                "id": "03.02.05.01"
              },
              "02_treatment_protocols": {
                "name": "Treatment Protocols",
                "id": "03.02.05.02"
              },
              "03_patient_care": {
                "name": "Patient Care",
                "id": "03.02.05.03"
              },
              "04_medical_procedures": {
                "name": "Medical Procedures",
                "id": "03.02.05.04"
              },
              "05_documentation": {
                "name": "Medical Documentation",
                "id": "03.02.05.05"
              }
            }
          },
          "06_surgery": {
            "name": "Surgery",
            "id": "03.02.06",
            "subcategories": {
              "01_general_surgery": {
                "name": "General Surgery",
                "id": "03.02.06.01"
              },
              "02_emergency_surgery": {
                "name": "Emergency Surgery",
                "id": "03.02.06.02"
              },
              "03_anesthesia": {
                "name": "Anesthesia",
                "id": "03.02.06.03"
              },
              "04_surgical_techniques": {
                "name": "Surgical Techniques",
                "id": "03.02.06.04"
              },
              "05_post_operative": {
                "name": "Post-operative Care",
                "id": "03.02.06.05"
              }
            }
          },
          "07_psychiatry": {
            "name": "Psychiatry",
            "id": "03.02.07"
          },
          "08_pediatrics": {
            "name": "Pediatrics",
            "id": "03.02.08"
          },
          "09_emergency_medicine": {
            "name": "Emergency Medicine",
            "id": "03.02.09"
          },
          "10_preventive_medicine": {
            "name": "Preventive Medicine",
            "id": "03.02.10"
          }
        }
      },
      "03_agriculture": {
        "name": "Agriculture",
        "id": "03.03",
        "subcategories": {
          "01_crop_science": {
            "name": "Crop Science",
            "id": "03.03.01",
            "subcategories": {
              "01_grains": {
                "name": "Grain Crops",
                "id": "03.03.01.01",
                "items": [
                  {
                    "id": "03.03.01.01.01",
                    "name": "Wheat cultivation"
                  },
                  {
                    "id": "03.03.01.01.02",
                    "name": "Rice farming"
                  },
                  {
                    "id": "03.03.01.01.03",
                    "name": "Corn/Maize"
                  },
                  {
                    "id": "03.03.01.01.04",
                    "name": "Barley"
                  },
                  {
                    "id": "03.03.01.01.05",
                    "name": "Oats"
                  }
                ]
              },
              "02_vegetables": {
                "name": "Vegetable Farming",
                "id": "03.03.01.02"
              },
              "03_fruits": {
                "name": "Fruit Cultivation",
                "id": "03.03.01.03"
              },
              "04_legumes": {
                "name": "Legumes",
                "id": "03.03.01.04"
              },
              "05_herbs_spices": {
                "name": "Herbs & Spices",
                "id": "03.03.01.05"
              }
            }
          },
          "02_animal_husbandry": {
            "name": "Animal Husbandry",
            "id": "03.03.02",
            "subcategories": {
              "01_cattle": {
                "name": "Cattle Farming",
                "id": "03.03.02.01"
              },
              "02_poultry": {
                "name": "Poultry Farming",
                "id": "03.03.02.02"
              },
              "03_sheep_goats": {
                "name": "Sheep & Goats",
                "id": "03.03.02.03"
              },
              "04_pigs": {
                "name": "Pig Farming",
                "id": "03.03.02.04"
              },
              "05_beekeeping": {
                "name": "Beekeeping",
                "id": "03.03.02.05"
              }
            }
          },
          "03_soil_science": {
            "name": "Soil Science",
            "id": "03.03.03",
            "subcategories": {
              "01_soil_types": {
                "name": "Soil Types",
                "id": "03.03.03.01"
              },
              "02_fertilizers": {
                "name": "Fertilizers",
                "id": "03.03.03.02"
              },
              "03_composting": {
                "name": "Composting",
                "id": "03.03.03.03"
              },
              "04_erosion_control": {
                "name": "Erosion Control",
                "id": "03.03.03.04"
              },
              "05_ph_management": {
                "name": "pH Management",
                "id": "03.03.03.05"
              }
            }
          },
          "04_horticulture": {
            "name": "Horticulture",
            "id": "03.03.04"
          },
          "05_aquaculture": {
            "name": "Aquaculture",
            "id": "03.03.05"
          },
          "06_forestry": {
            "name": "Forestry",
            "id": "03.03.06"
          },
          "07_agricultural_engineering": {
            "name": "Agricultural Engineering",
            "id": "03.03.07"
          },
          "08_permaculture": {
            "name": "Permaculture",
            "id": "03.03.08"
          },
          "09_hydroponics": {
            "name": "Hydroponics",
            "id": "03.03.09"
          },
          "10_organic_farming": {
            "name": "Organic Farming",
            "id": "03.03.10"
          }
        }
      },
      "04_architecture": {
        "name": "Architecture",
        "id": "03.04"
      },
      "05_manufacturing": {
        "name": "Manufacturing",
        "id": "03.05",
        "subcategories": {
          "01_metalworking": {
            "name": "Metalworking",
            "id": "03.05.01",
            "subcategories": {
              "01_casting": {
                "name": "Metal Casting",
                "id": "03.05.01.01",
                "items": [
                  {
                    "id": "03.05.01.01.01",
                    "name": "Sand casting"
                  },
                  {
                    "id": "03.05.01.01.02",
                    "name": "Die casting"
                  },
                  {
                    "id": "03.05.01.01.03",
                    "name": "Investment casting"
                  },
                  {
                    "id": "03.05.01.01.04",
                    "name": "Continuous casting"
                  },
                  {
                    "id": "03.05.01.01.05",
                    "name": "Centrifugal casting"
                  }
                ]
              },
              "02_forging": {
                "name": "Forging",
                "id": "03.05.01.02"
              },
              "03_machining": {
                "name": "Machining",
                "id": "03.05.01.03"
              },
              "04_sheet_metal": {
                "name": "Sheet Metal Working",
                "id": "03.05.01.04"
              },
              "05_heat_treatment": {
                "name": "Heat Treatment",
                "id": "03.05.01.05"
              }
            }
          },
          "02_plastics": {
            "name": "Plastics Manufacturing",
            "id": "03.05.02",
            "subcategories": {
              "01_injection_molding": {
                "name": "Injection Molding",
                "id": "03.05.02.01"
              },
              "02_extrusion": {
                "name": "Extrusion",
                "id": "03.05.02.02"
              },
              "03_blow_molding": {
                "name": "Blow Molding",
                "id": "03.05.02.03"
              },
              "04_thermoforming": {
                "name": "Thermoforming",
                "id": "03.05.02.04"
              },
              "05_3d_printing": {
                "name": "3D Printing",
                "id": "03.05.02.05"
              }
            }
          },
          "03_textiles": {
            "name": "Textile Manufacturing",
            "id": "03.05.03"
          },
          "04_electronics_manufacturing": {
            "name": "Electronics Manufacturing",
            "id": "03.05.04"
          },
          "05_assembly": {
            "name": "Assembly Systems",
            "id": "03.05.05"
          },
          "06_quality_control": {
            "name": "Quality Control",
            "id": "03.05.06"
          },
          "07_automation": {
            "name": "Manufacturing Automation",
            "id": "03.05.07"
          },
          "08_lean_manufacturing": {
            "name": "Lean Manufacturing",
            "id": "03.05.08"
          },
          "09_supply_chain": {
            "name": "Supply Chain Management",
            "id": "03.05.09"
          },
          "10_safety": {
            "name": "Manufacturing Safety",
            "id": "03.05.10"
          }
        }
      },
      "06_transportation": {
        "name": "Transportation",
        "id": "03.06",
        "subcategories": {
          "01_automotive": {
            "name": "Automotive Technology",
            "id": "03.06.01",
            "subcategories": {
              "01_engine_technology": {
                "name": "Engine Technology",
                "id": "03.06.01.01"
              },
              "02_electric_vehicles": {
                "name": "Electric Vehicles",
                "id": "03.06.01.02"
              },
              "03_autonomous_vehicles": {
                "name": "Autonomous Vehicles",
                "id": "03.06.01.03"
              },
              "04_vehicle_safety": {
                "name": "Vehicle Safety",
                "id": "03.06.01.04"
              },
              "05_maintenance": {
                "name": "Vehicle Maintenance",
                "id": "03.06.01.05"
              }
            }
          },
          "02_aviation": {
            "name": "Aviation",
            "id": "03.06.02",
            "subcategories": {
              "01_aircraft_design": {
                "name": "Aircraft Design",
                "id": "03.06.02.01"
              },
              "02_flight_systems": {
                "name": "Flight Systems",
                "id": "03.06.02.02"
              },
              "03_air_traffic": {
                "name": "Air Traffic Control",
                "id": "03.06.02.03"
              },
              "04_maintenance": {
                "name": "Aircraft Maintenance",
                "id": "03.06.02.04"
              },
              "05_pilot_training": {
                "name": "Pilot Training",
                "id": "03.06.02.05"
              }
            }
          },
          "03_maritime": {
            "name": "Maritime",
            "id": "03.06.03"
          },
          "04_rail": {
            "name": "Rail Transport",
            "id": "03.06.04"
          },
          "05_public_transit": {
            "name": "Public Transit",
            "id": "03.06.05"
          },
          "06_logistics": {
            "name": "Logistics",
            "id": "03.06.06"
          },
          "07_infrastructure": {
            "name": "Transport Infrastructure",
            "id": "03.06.07"
          },
          "08_traffic_management": {
            "name": "Traffic Management",
            "id": "03.06.08"
          },
          "09_alternative_transport": {
            "name": "Alternative Transport",
            "id": "03.06.09"
          },
          "10_space_transport": {
            "name": "Space Transportation",
            "id": "03.06.10"
          }
        }
      },
      "07_energy": {
        "name": "Energy",
        "id": "03.07",
        "subcategories": {
          "01_renewable_energy": {
            "name": "Renewable Energy",
            "id": "03.07.01",
            "subcategories": {
              "01_solar": {
                "name": "Solar Energy",
                "id": "03.07.01.01",
                "items": [
                  {
                    "id": "03.07.01.01.01",
                    "name": "Photovoltaic systems"
                  },
                  {
                    "id": "03.07.01.01.02",
                    "name": "Solar thermal"
                  },
                  {
                    "id": "03.07.01.01.03",
                    "name": "Concentrated solar power"
                  },
                  {
                    "id": "03.07.01.01.04",
                    "name": "Solar panel manufacturing"
                  },
                  {
                    "id": "03.07.01.01.05",
                    "name": "Off-grid solar setup"
                  }
                ]
              },
              "02_wind": {
                "name": "Wind Energy",
                "id": "03.07.01.02",
                "items": [
                  {
                    "id": "03.07.01.02.01",
                    "name": "Wind turbine design"
                  },
                  {
                    "id": "03.07.01.02.02",
                    "name": "Small-scale wind"
                  },
                  {
                    "id": "03.07.01.02.03",
                    "name": "Wind farm planning"
                  },
                  {
                    "id": "03.07.01.02.04",
                    "name": "Vertical axis turbines"
                  },
                  {
                    "id": "03.07.01.02.05",
                    "name": "Wind resource assessment"
                  }
                ]
              },
              "03_hydro": {
                "name": "Hydroelectric",
                "id": "03.07.01.03"
              },
              "04_geothermal": {
                "name": "Geothermal",
                "id": "03.07.01.04"
              },
              "05_biomass": {
                "name": "Biomass Energy",
                "id": "03.07.01.05"
              }
            }
          },
          "02_fossil_fuels": {
            "name": "Fossil Fuels",
            "id": "03.07.02",
            "subcategories": {
              "01_oil_extraction": {
                "name": "Oil Extraction",
                "id": "03.07.02.01"
              },
              "02_refining": {
                "name": "Refining Processes",
                "id": "03.07.02.02"
              },
              "03_coal": {
                "name": "Coal Technology",
                "id": "03.07.02.03"
              },
              "04_natural_gas": {
                "name": "Natural Gas",
                "id": "03.07.02.04"
              },
              "05_carbon_capture": {
                "name": "Carbon Capture",
                "id": "03.07.02.05"
              }
            }
          },
          "03_nuclear": {
            "name": "Nuclear Energy",
            "id": "03.07.03",
            "subcategories": {
              "01_fission": {
                "name": "Nuclear Fission",
                "id": "03.07.03.01"
              },
              "02_fusion": {
                "name": "Nuclear Fusion",
                "id": "03.07.03.02"
              },
              "03_reactor_design": {
                "name": "Reactor Design",
                "id": "03.07.03.03"
              },
              "04_waste_management": {
                "name": "Nuclear Waste",
                "id": "03.07.03.04"
              },
              "05_safety_protocols": {
                "name": "Safety Protocols",
                "id": "03.07.03.05"
              }
            }
          },
          "04_energy_storage": {
            "name": "Energy Storage",
            "id": "03.07.04",
            "subcategories": {
              "01_batteries": {
                "name": "Battery Technology",
                "id": "03.07.04.01"
              },
              "02_mechanical": {
                "name": "Mechanical Storage",
                "id": "03.07.04.02"
              },
              "03_chemical": {
                "name": "Chemical Storage",
                "id": "03.07.04.03"
              },
              "04_thermal": {
                "name": "Thermal Storage",
                "id": "03.07.04.04"
              },
              "05_hydrogen": {
                "name": "Hydrogen Storage",
                "id": "03.07.04.05"
              }
            }
          },
          "05_power_distribution": {
            "name": "Power Distribution",
            "id": "03.07.05"
          }
        }
      },
      "08_telecommunications": {
        "name": "Telecommunications",
        "id": "03.08"
      },
      "09_biotechnology": {
        "name": "Biotechnology",
        "id": "03.09"
      },
      "10_nanotechnology": {
        "name": "Nanotechnology",
        "id": "03.10"
      }
    }
  },
  "04_social_sciences": {
    "name": "Social Sciences",
    "id": "04",
    "description": "Study of human society",
    "subcategories": {
      "01_psychology": {
        "name": "Psychology",
        "id": "04.01",
        "subcategories": {
          "01_cognitive_psychology": {
            "name": "Cognitive Psychology",
            "id": "04.01.01"
          },
          "02_developmental_psychology": {
            "name": "Developmental Psychology",
            "id": "04.01.02"
          },
          "03_social_psychology": {
            "name": "Social Psychology",
            "id": "04.01.03"
          },
          "04_clinical_psychology": {
            "name": "Clinical Psychology",
            "id": "04.01.04"
          },
          "05_neuropsychology": {
            "name": "Neuropsychology",
            "id": "04.01.05"
          }
        }
      },
      "02_sociology": {
        "name": "Sociology",
        "id": "04.02"
      },
      "03_anthropology": {
        "name": "Anthropology",
        "id": "04.03"
      },
      "04_economics": {
        "name": "Economics",
        "id": "04.04",
        "subcategories": {
          "01_microeconomics": {
            "name": "Microeconomics",
            "id": "04.04.01",
            "subcategories": {
              "01_supply_demand": {
                "name": "Supply and Demand",
                "id": "04.04.01.01",
                "items": [
                  {
                    "id": "04.04.01.01.01",
                    "name": "Market equilibrium"
                  },
                  {
                    "id": "04.04.01.01.02",
                    "name": "Price elasticity"
                  },
                  {
                    "id": "04.04.01.01.03",
                    "name": "Consumer surplus"
                  },
                  {
                    "id": "04.04.01.01.04",
                    "name": "Producer surplus"
                  },
                  {
                    "id": "04.04.01.01.05",
                    "name": "Market failures"
                  }
                ]
              },
              "02_consumer_theory": {
                "name": "Consumer Theory",
                "id": "04.04.01.02"
              },
              "03_production_theory": {
                "name": "Production Theory",
                "id": "04.04.01.03"
              },
              "04_market_structures": {
                "name": "Market Structures",
                "id": "04.04.01.04"
              },
              "05_game_theory": {
                "name": "Game Theory Applications",
                "id": "04.04.01.05"
              }
            }
          },
          "02_macroeconomics": {
            "name": "Macroeconomics",
            "id": "04.04.02",
            "subcategories": {
              "01_gdp": {
                "name": "GDP and Growth",
                "id": "04.04.02.01"
              },
              "02_inflation": {
                "name": "Inflation",
                "id": "04.04.02.02"
              },
              "03_unemployment": {
                "name": "Unemployment",
                "id": "04.04.02.03"
              },
              "04_monetary_policy": {
                "name": "Monetary Policy",
                "id": "04.04.02.04"
              },
              "05_fiscal_policy": {
                "name": "Fiscal Policy",
                "id": "04.04.02.05"
              }
            }
          },
          "03_econometrics": {
            "name": "Econometrics",
            "id": "04.04.03"
          },
          "04_behavioral_economics": {
            "name": "Behavioral Economics",
            "id": "04.04.04"
          },
          "05_international_economics": {
            "name": "International Economics",
            "id": "04.04.05"
          },
          "06_development_economics": {
            "name": "Development Economics",
            "id": "04.04.06"
          },
          "07_environmental_economics": {
            "name": "Environmental Economics",
            "id": "04.04.07"
          },
          "08_financial_economics": {
            "name": "Financial Economics",
            "id": "04.04.08"
          },
          "09_labor_economics": {
            "name": "Labor Economics",
            "id": "04.04.09"
          },
          "10_economic_history": {
            "name": "Economic History",
            "id": "04.04.10"
          }
        }
      },
      "05_political_science": {
        "name": "Political Science",
        "id": "04.05"
      },
      "06_law": {
        "name": "Law",
        "id": "04.06"
      },
      "07_education": {
        "name": "Education",
        "id": "04.07"
      },
      "08_geography": {
        "name": "Geography",
        "id": "04.08"
      },
      "09_demography": {
        "name": "Demography",
        "id": "04.09"
      },
      "10_archaeology": {
        "name": "Archaeology",
        "id": "04.10"
      }
    }
  },
  "05_humanities": {
    "name": "Humanities",
    "id": "05",
    "description": "Study of human culture",
    "subcategories": {
      "01_history": {
        "name": "History",
        "id": "05.01",
        "subcategories": {
          "01_ancient_history": {
            "name": "Ancient History",
            "id": "05.01.01",
            "subcategories": {
              "01_mesopotamia": {
                "name": "Mesopotamian Civilizations",
                "id": "05.01.01.01",
                "items": [
                  {
                    "id": "05.01.01.01.01",
                    "name": "Sumerian civilization"
                  },
                  {
                    "id": "05.01.01.01.02",
                    "name": "Babylonian empire"
                  },
                  {
                    "id": "05.01.01.01.03",
                    "name": "Assyrian empire"
                  },
                  {
                    "id": "05.01.01.01.04",
                    "name": "Akkadian empire"
                  },
                  {
                    "id": "05.01.01.01.05",
                    "name": "Cuneiform writing"
                  }
                ]
              },
              "02_egypt": {
                "name": "Ancient Egypt",
                "id": "05.01.01.02"
              },
              "03_greece": {
                "name": "Ancient Greece",
                "id": "05.01.01.03"
              },
              "04_rome": {
                "name": "Roman Empire",
                "id": "05.01.01.04"
              },
              "05_china": {
                "name": "Ancient China",
                "id": "05.01.01.05"
              },
              "06_india": {
                "name": "Ancient India",
                "id": "05.01.01.06"
              },
              "07_americas": {
                "name": "Pre-Columbian Americas",
                "id": "05.01.01.07"
              },
              "08_africa": {
                "name": "Ancient Africa",
                "id": "05.01.01.08"
              },
              "09_near_east": {
                "name": "Ancient Near East",
                "id": "05.01.01.09"
              },
              "10_archaeology": {
                "name": "Archaeological Methods",
                "id": "05.01.01.10"
              }
            }
          },
          "02_medieval_history": {
            "name": "Medieval History",
            "id": "05.01.02",
            "subcategories": {
              "01_early_medieval": {
                "name": "Early Medieval (500-1000)",
                "id": "05.01.02.01"
              },
              "02_high_medieval": {
                "name": "High Medieval (1000-1300)",
                "id": "05.01.02.02"
              },
              "03_late_medieval": {
                "name": "Late Medieval (1300-1500)",
                "id": "05.01.02.03"
              },
              "04_crusades": {
                "name": "The Crusades",
                "id": "05.01.02.04"
              },
              "05_black_death": {
                "name": "The Black Death",
                "id": "05.01.02.05"
              }
            }
          },
          "03_modern_history": {
            "name": "Modern History",
            "id": "05.01.03",
            "subcategories": {
              "01_renaissance": {
                "name": "Renaissance",
                "id": "05.01.03.01"
              },
              "02_age_of_exploration": {
                "name": "Age of Exploration",
                "id": "05.01.03.02"
              },
              "03_enlightenment": {
                "name": "Enlightenment",
                "id": "05.01.03.03"
              },
              "04_industrial_revolution": {
                "name": "Industrial Revolution",
                "id": "05.01.03.04"
              },
              "05_colonialism": {
                "name": "Colonialism",
                "id": "05.01.03.05"
              }
            }
          },
          "04_contemporary_history": {
            "name": "Contemporary History",
            "id": "05.01.04",
            "subcategories": {
              "01_world_wars": {
                "name": "World Wars",
                "id": "05.01.04.01"
              },
              "02_cold_war": {
                "name": "Cold War",
                "id": "05.01.04.02"
              },
              "03_decolonization": {
                "name": "Decolonization",
                "id": "05.01.04.03"
              },
              "04_globalization": {
                "name": "Globalization",
                "id": "05.01.04.04"
              },
              "05_digital_age": {
                "name": "Digital Age",
                "id": "05.01.04.05"
              }
            }
          },
          "05_military_history": {
            "name": "Military History",
            "id": "05.01.05"
          }
        }
      },
      "02_philosophy": {
        "name": "Philosophy",
        "id": "05.02",
        "subcategories": {
          "01_metaphysics": {
            "name": "Metaphysics",
            "id": "05.02.01",
            "subcategories": {
              "01_ontology": {
                "name": "Ontology",
                "id": "05.02.01.01",
                "items": [
                  {
                    "id": "05.02.01.01.01",
                    "name": "Being and existence"
                  },
                  {
                    "id": "05.02.01.01.02",
                    "name": "Categories of being"
                  },
                  {
                    "id": "05.02.01.01.03",
                    "name": "Universals problem"
                  },
                  {
                    "id": "05.02.01.01.04",
                    "name": "Identity and change"
                  },
                  {
                    "id": "05.02.01.01.05",
                    "name": "Possible worlds"
                  }
                ]
              },
              "02_cosmology": {
                "name": "Philosophical Cosmology",
                "id": "05.02.01.02"
              },
              "03_mind": {
                "name": "Philosophy of Mind",
                "id": "05.02.01.03"
              },
              "04_free_will": {
                "name": "Free Will",
                "id": "05.02.01.04"
              },
              "05_time_space": {
                "name": "Time and Space",
                "id": "05.02.01.05"
              }
            }
          },
          "02_epistemology": {
            "name": "Epistemology",
            "id": "05.02.02",
            "subcategories": {
              "01_knowledge": {
                "name": "Theory of Knowledge",
                "id": "05.02.02.01"
              },
              "02_skepticism": {
                "name": "Skepticism",
                "id": "05.02.02.02"
              },
              "03_justification": {
                "name": "Justification",
                "id": "05.02.02.03"
              },
              "04_truth": {
                "name": "Theories of Truth",
                "id": "05.02.02.04"
              },
              "05_perception": {
                "name": "Perception",
                "id": "05.02.02.05"
              }
            }
          },
          "03_ethics": {
            "name": "Ethics",
            "id": "05.02.03",
            "subcategories": {
              "01_normative": {
                "name": "Normative Ethics",
                "id": "05.02.03.01"
              },
              "02_applied": {
                "name": "Applied Ethics",
                "id": "05.02.03.02"
              },
              "03_meta_ethics": {
                "name": "Meta-ethics",
                "id": "05.02.03.03"
              },
              "04_virtue_ethics": {
                "name": "Virtue Ethics",
                "id": "05.02.03.04"
              },
              "05_consequentialism": {
                "name": "Consequentialism",
                "id": "05.02.03.05"
              }
            }
          },
          "04_aesthetics": {
            "name": "Aesthetics",
            "id": "05.02.04"
          },
          "05_logic": {
            "name": "Logic",
            "id": "05.02.05"
          }
        }
      },
      "03_linguistics": {
        "name": "Linguistics",
        "id": "05.03"
      },
      "04_literature": {
        "name": "Literature",
        "id": "05.04"
      },
      "05_religious_studies": {
        "name": "Religious Studies",
        "id": "05.05"
      },
      "06_cultural_studies": {
        "name": "Cultural Studies",
        "id": "05.06"
      },
      "07_classics": {
        "name": "Classics",
        "id": "05.07"
      },
      "08_media_studies": {
        "name": "Media Studies",
        "id": "05.08"
      },
      "09_gender_studies": {
        "name": "Gender Studies",
        "id": "05.09"
      },
      "10_ethnic_studies": {
        "name": "Ethnic Studies",
        "id": "05.10"
      }
    }
  },
  "06_arts": {
    "name": "Arts & Creative Expression",
    "id": "06",
    "description": "Creative and performing arts",
    "subcategories": {
      "01_visual_arts": {
        "name": "Visual Arts",
        "id": "06.01",
        "subcategories": {
          "01_painting": {
            "name": "Painting",
            "id": "06.01.01",
            "subcategories": {
              "01_techniques": {
                "name": "Painting Techniques",
                "id": "06.01.01.01",
                "items": [
                  {
                    "id": "06.01.01.01.01",
                    "name": "Oil painting"
                  },
                  {
                    "id": "06.01.01.01.02",
                    "name": "Watercolor"
                  },
                  {
                    "id": "06.01.01.01.03",
                    "name": "Acrylic"
                  },
                  {
                    "id": "06.01.01.01.04",
                    "name": "Fresco"
                  },
                  {
                    "id": "06.01.01.01.05",
                    "name": "Tempera"
                  }
                ]
              },
              "02_styles": {
                "name": "Art Movements",
                "id": "06.01.01.02"
              },
              "03_color_theory": {
                "name": "Color Theory",
                "id": "06.01.01.03"
              },
              "04_composition": {
                "name": "Composition",
                "id": "06.01.01.04"
              },
              "05_restoration": {
                "name": "Art Restoration",
                "id": "06.01.01.05"
              }
            }
          },
          "02_sculpture": {
            "name": "Sculpture",
            "id": "06.01.02",
            "subcategories": {
              "01_materials": {
                "name": "Sculpting Materials",
                "id": "06.01.02.01"
              },
              "02_techniques": {
                "name": "Sculpting Techniques",
                "id": "06.01.02.02"
              },
              "03_casting": {
                "name": "Casting Methods",
                "id": "06.01.02.03"
              },
              "04_carving": {
                "name": "Carving",
                "id": "06.01.02.04"
              },
              "05_installation": {
                "name": "Installation Art",
                "id": "06.01.02.05"
              }
            }
          },
          "03_photography": {
            "name": "Photography",
            "id": "06.01.03",
            "subcategories": {
              "01_camera_basics": {
                "name": "Camera Fundamentals",
                "id": "06.01.03.01"
              },
              "02_composition": {
                "name": "Photographic Composition",
                "id": "06.01.03.02"
              },
              "03_lighting": {
                "name": "Lighting Techniques",
                "id": "06.01.03.03"
              },
              "04_darkroom": {
                "name": "Darkroom Processes",
                "id": "06.01.03.04"
              },
              "05_digital_processing": {
                "name": "Digital Processing",
                "id": "06.01.03.05"
              }
            }
          },
          "04_digital_art": {
            "name": "Digital Art",
            "id": "06.01.04"
          },
          "05_printmaking": {
            "name": "Printmaking",
            "id": "06.01.05"
          }
        }
      },
      "02_performing_arts": {
        "name": "Performing Arts",
        "id": "06.02",
        "subcategories": {
          "01_music": {
            "name": "Music",
            "id": "06.02.01",
            "subcategories": {
              "01_theory": {
                "name": "Music Theory",
                "id": "06.02.01.01",
                "items": [
                  {
                    "id": "06.02.01.01.01",
                    "name": "Notation"
                  },
                  {
                    "id": "06.02.01.01.02",
                    "name": "Harmony"
                  },
                  {
                    "id": "06.02.01.01.03",
                    "name": "Rhythm"
                  },
                  {
                    "id": "06.02.01.01.04",
                    "name": "Scales and modes"
                  },
                  {
                    "id": "06.02.01.01.05",
                    "name": "Counterpoint"
                  }
                ]
              },
              "02_instruments": {
                "name": "Musical Instruments",
                "id": "06.02.01.02"
              },
              "03_composition": {
                "name": "Composition",
                "id": "06.02.01.03"
              },
              "04_performance": {
                "name": "Performance",
                "id": "06.02.01.04"
              },
              "05_recording": {
                "name": "Recording Technology",
                "id": "06.02.01.05"
              }
            }
          },
          "02_dance": {
            "name": "Dance",
            "id": "06.02.02"
          },
          "03_theater": {
            "name": "Theater",
            "id": "06.02.03"
          },
          "04_film": {
            "name": "Film",
            "id": "06.02.04"
          },
          "05_opera": {
            "name": "Opera",
            "id": "06.02.05"
          }
        }
      },
      "03_design": {
        "name": "Design",
        "id": "06.03",
        "subcategories": {
          "01_graphic_design": {
            "name": "Graphic Design",
            "id": "06.03.01"
          },
          "02_industrial_design": {
            "name": "Industrial Design",
            "id": "06.03.02"
          },
          "03_fashion_design": {
            "name": "Fashion Design",
            "id": "06.03.03"
          },
          "04_interior_design": {
            "name": "Interior Design",
            "id": "06.03.04"
          },
          "05_ux_design": {
            "name": "UX/UI Design",
            "id": "06.03.05"
          }
        }
      },
      "04_crafts": {
        "name": "Crafts",
        "id": "06.04",
        "subcategories": {
          "01_pottery": {
            "name": "Pottery & Ceramics",
            "id": "06.04.01"
          },
          "02_weaving": {
            "name": "Weaving & Textiles",
            "id": "06.04.02"
          },
          "03_jewelry": {
            "name": "Jewelry Making",
            "id": "06.04.03"
          },
          "04_glasswork": {
            "name": "Glassworking",
            "id": "06.04.04"
          },
          "05_bookbinding": {
            "name": "Bookbinding",
            "id": "06.04.05"
          }
        }
      },
      "05_culinary_arts": {
        "name": "Culinary Arts",
        "id": "06.05"
      }
    }
  },
  "07_practical_skills": {
    "name": "Practical Skills & Trades",
    "id": "07",
    "description": "Hands-on skills and craftsmanship",
    "subcategories": {
      "01_construction": {
        "name": "Construction",
        "id": "07.01",
        "subcategories": {
          "01_foundations": {
            "name": "Foundations",
            "id": "07.01.01",
            "subcategories": {
              "01_concrete": {
                "name": "Concrete Work",
                "id": "07.01.01.01",
                "items": [
                  {
                    "id": "07.01.01.01.01",
                    "name": "Mixing ratios"
                  },
                  {
                    "id": "07.01.01.01.02",
                    "name": "Pouring techniques"
                  },
                  {
                    "id": "07.01.01.01.03",
                    "name": "Reinforcement"
                  },
                  {
                    "id": "07.01.01.01.04",
                    "name": "Curing process"
                  },
                  {
                    "id": "07.01.01.01.05",
                    "name": "Foundation types"
                  }
                ]
              },
              "02_excavation": {
                "name": "Excavation",
                "id": "07.01.01.02"
              },
              "03_drainage": {
                "name": "Drainage Systems",
                "id": "07.01.01.03"
              },
              "04_waterproofing": {
                "name": "Waterproofing",
                "id": "07.01.01.04"
              },
              "05_load_calculations": {
                "name": "Load Calculations",
                "id": "07.01.01.05"
              }
            }
          },
          "02_framing": {
            "name": "Framing",
            "id": "07.01.02",
            "subcategories": {
              "01_wood_framing": {
                "name": "Wood Framing",
                "id": "07.01.02.01"
              },
              "02_steel_framing": {
                "name": "Steel Framing",
                "id": "07.01.02.02"
              },
              "03_roof_framing": {
                "name": "Roof Framing",
                "id": "07.01.02.03"
              },
              "04_floor_systems": {
                "name": "Floor Systems",
                "id": "07.01.02.04"
              },
              "05_load_bearing": {
                "name": "Load Bearing Walls",
                "id": "07.01.02.05"
              }
            }
          },
          "03_masonry": {
            "name": "Masonry",
            "id": "07.01.03"
          },
          "04_roofing": {
            "name": "Roofing",
            "id": "07.01.04"
          },
          "05_insulation": {
            "name": "Insulation",
            "id": "07.01.05"
          }
        }
      },
      "02_mechanics": {
        "name": "Mechanics",
        "id": "07.02",
        "subcategories": {
          "01_engine_repair": {
            "name": "Engine Repair",
            "id": "07.02.01",
            "subcategories": {
              "01_diagnostics": {
                "name": "Engine Diagnostics",
                "id": "07.02.01.01"
              },
              "02_combustion_engines": {
                "name": "Combustion Engines",
                "id": "07.02.01.02"
              },
              "03_diesel_engines": {
                "name": "Diesel Engines",
                "id": "07.02.01.03"
              },
              "04_small_engines": {
                "name": "Small Engines",
                "id": "07.02.01.04"
              },
              "05_rebuild_procedures": {
                "name": "Rebuild Procedures",
                "id": "07.02.01.05"
              }
            }
          },
          "02_transmission": {
            "name": "Transmission Systems",
            "id": "07.02.02"
          },
          "03_suspension": {
            "name": "Suspension & Steering",
            "id": "07.02.03"
          },
          "04_brakes": {
            "name": "Brake Systems",
            "id": "07.02.04"
          },
          "05_hydraulics": {
            "name": "Hydraulic Systems",
            "id": "07.02.05"
          }
        }
      },
      "03_electronics": {
        "name": "Electronics",
        "id": "07.03",
        "subcategories": {
          "01_basic_circuits": {
            "name": "Basic Circuits",
            "id": "07.03.01",
            "subcategories": {
              "01_components": {
                "name": "Electronic Components",
                "id": "07.03.01.01",
                "items": [
                  {
                    "id": "07.03.01.01.01",
                    "name": "Resistors"
                  },
                  {
                    "id": "07.03.01.01.02",
                    "name": "Capacitors"
                  },
                  {
                    "id": "07.03.01.01.03",
                    "name": "Transistors"
                  },
                  {
                    "id": "07.03.01.01.04",
                    "name": "Diodes"
                  },
                  {
                    "id": "07.03.01.01.05",
                    "name": "Integrated circuits"
                  }
                ]
              },
              "02_circuit_design": {
                "name": "Circuit Design",
                "id": "07.03.01.02"
              },
              "03_soldering": {
                "name": "Soldering Techniques",
                "id": "07.03.01.03"
              },
              "04_testing": {
                "name": "Testing & Measurement",
                "id": "07.03.01.04"
              },
              "05_troubleshooting": {
                "name": "Troubleshooting",
                "id": "07.03.01.05"
              }
            }
          },
          "02_microcontrollers": {
            "name": "Microcontrollers",
            "id": "07.03.02"
          },
          "03_power_supplies": {
            "name": "Power Supplies",
            "id": "07.03.03"
          },
          "04_radio_electronics": {
            "name": "Radio Electronics",
            "id": "07.03.04"
          },
          "05_repair": {
            "name": "Electronics Repair",
            "id": "07.03.05"
          }
        }
      },
      "04_plumbing": {
        "name": "Plumbing",
        "id": "07.04",
        "subcategories": {
          "01_pipe_systems": {
            "name": "Pipe Systems",
            "id": "07.04.01"
          },
          "02_fixtures": {
            "name": "Fixtures Installation",
            "id": "07.04.02"
          },
          "03_water_heating": {
            "name": "Water Heating",
            "id": "07.04.03"
          },
          "04_drainage": {
            "name": "Drainage Systems",
            "id": "07.04.04"
          },
          "05_repair": {
            "name": "Plumbing Repair",
            "id": "07.04.05"
          }
        }
      },
      "05_carpentry": {
        "name": "Carpentry",
        "id": "07.05",
        "subcategories": {
          "01_joinery": {
            "name": "Joinery",
            "id": "07.05.01"
          },
          "02_furniture": {
            "name": "Furniture Making",
            "id": "07.05.02"
          },
          "03_cabinetry": {
            "name": "Cabinetry",
            "id": "07.05.03"
          },
          "04_finishing": {
            "name": "Wood Finishing",
            "id": "07.05.04"
          },
          "05_restoration": {
            "name": "Wood Restoration",
            "id": "07.05.05"
          }
        }
      },
      "06_welding": {
        "name": "Welding",
        "id": "07.06",
        "subcategories": {
          "01_arc_welding": {
            "name": "Arc Welding",
            "id": "07.06.01"
          },
          "02_mig_welding": {
            "name": "MIG Welding",
            "id": "07.06.02"
          },
          "03_tig_welding": {
            "name": "TIG Welding",
            "id": "07.06.03"
          },
          "04_gas_welding": {
            "name": "Gas Welding",
            "id": "07.06.04"
          },
          "05_welding_safety": {
            "name": "Welding Safety",
            "id": "07.06.05"
          }
        }
      },
      "07_gardening": {
        "name": "Gardening",
        "id": "07.07",
        "subcategories": {
          "01_soil_prep": {
            "name": "Soil Preparation",
            "id": "07.07.01"
          },
          "02_planting": {
            "name": "Planting Techniques",
            "id": "07.07.02"
          },
          "03_pruning": {
            "name": "Pruning",
            "id": "07.07.03"
          },
          "04_pest_control": {
            "name": "Pest Control",
            "id": "07.07.04"
          },
          "05_composting": {
            "name": "Composting",
            "id": "07.07.05"
          }
        }
      },
      "08_cooking": {
        "name": "Cooking",
        "id": "07.08",
        "subcategories": {
          "01_basic_techniques": {
            "name": "Basic Techniques",
            "id": "07.08.01"
          },
          "02_baking": {
            "name": "Baking",
            "id": "07.08.02"
          },
          "03_preservation": {
            "name": "Food Preservation",
            "id": "07.08.03"
          },
          "04_nutrition": {
            "name": "Nutrition",
            "id": "07.08.04"
          },
          "05_special_diets": {
            "name": "Special Diets",
            "id": "07.08.05"
          }
        }
      },
      "09_sewing": {
        "name": "Sewing",
        "id": "07.09"
      },
      "10_automotive": {
        "name": "Automotive",
        "id": "07.10"
      }
    }
  },
  "08_survival_emergency": {
    "name": "Survival & Emergency Preparedness",
    "id": "08",
    "description": "Critical knowledge for emergencies",
    "subcategories": {
      "01_first_aid": {
        "name": "First Aid & Medical",
        "id": "08.01",
        "subcategories": {
          "01_basic_first_aid": {
            "name": "Basic First Aid",
            "id": "08.01.01",
            "subcategories": {
              "01_cpr": {
                "name": "CPR & Resuscitation",
                "id": "08.01.01.01",
                "items": [
                  {
                    "id": "08.01.01.01.01",
                    "name": "Adult CPR"
                  },
                  {
                    "id": "08.01.01.01.02",
                    "name": "Child CPR"
                  },
                  {
                    "id": "08.01.01.01.03",
                    "name": "AED usage"
                  },
                  {
                    "id": "08.01.01.01.04",
                    "name": "Heimlich maneuver"
                  },
                  {
                    "id": "08.01.01.01.05",
                    "name": "Recovery position"
                  }
                ]
              },
              "02_wound_care": {
                "name": "Wound Care",
                "id": "08.01.01.02"
              },
              "03_burns": {
                "name": "Burn Treatment",
                "id": "08.01.01.03"
              },
              "04_fractures": {
                "name": "Fracture Management",
                "id": "08.01.01.04"
              },
              "05_shock": {
                "name": "Shock Treatment",
                "id": "08.01.01.05"
              }
            }
          },
          "02_trauma_care": {
            "name": "Trauma Care",
            "id": "08.01.02",
            "subcategories": {
              "01_bleeding_control": {
                "name": "Bleeding Control",
                "id": "08.01.02.01"
              },
              "02_tourniquets": {
                "name": "Tourniquet Application",
                "id": "08.01.02.02"
              },
              "03_chest_wounds": {
                "name": "Chest Wound Management",
                "id": "08.01.02.03"
              },
              "04_head_injuries": {
                "name": "Head Injury Care",
                "id": "08.01.02.04"
              },
              "05_spinal_injuries": {
                "name": "Spinal Injury Management",
                "id": "08.01.02.05"
              }
            }
          },
          "03_wilderness_medicine": {
            "name": "Wilderness Medicine",
            "id": "08.01.03"
          },
          "04_emergency_childbirth": {
            "name": "Emergency Childbirth",
            "id": "08.01.04"
          },
          "05_medication_knowledge": {
            "name": "Medication Knowledge",
            "id": "08.01.05",
            "subcategories": {
              "01_antibiotics": {
                "name": "Antibiotics",
                "id": "08.01.05.01"
              },
              "02_pain_management": {
                "name": "Pain Management",
                "id": "08.01.05.02"
              },
              "03_herbal_medicine": {
                "name": "Herbal Medicine",
                "id": "08.01.05.03"
              },
              "04_medication_production": {
                "name": "Basic Medication Production",
                "id": "08.01.05.04"
              },
              "05_dosages": {
                "name": "Dosage Calculations",
                "id": "08.01.05.05"
              }
            }
          }
        }
      },
      "02_water_procurement": {
        "name": "Water Procurement & Purification",
        "id": "08.02",
        "subcategories": {
          "01_water_sources": {
            "name": "Finding Water Sources",
            "id": "08.02.01",
            "items": [
              {
                "id": "08.02.01.01",
                "name": "Groundwater location"
              },
              {
                "id": "08.02.01.02",
                "name": "Rainwater collection"
              },
              {
                "id": "08.02.01.03",
                "name": "Dew collection"
              },
              {
                "id": "08.02.01.04",
                "name": "Solar stills"
              },
              {
                "id": "08.02.01.05",
                "name": "Plant moisture extraction"
              }
            ]
          },
          "02_purification_methods": {
            "name": "Purification Methods",
            "id": "08.02.02",
            "items": [
              {
                "id": "08.02.02.01",
                "name": "Boiling"
              },
              {
                "id": "08.02.02.02",
                "name": "Chemical treatment"
              },
              {
                "id": "08.02.02.03",
                "name": "UV sterilization"
              },
              {
                "id": "08.02.02.04",
                "name": "Filtration systems"
              },
              {
                "id": "08.02.02.05",
                "name": "Distillation"
              }
            ]
          },
          "03_storage": {
            "name": "Water Storage",
            "id": "08.02.03"
          },
          "04_testing": {
            "name": "Water Testing",
            "id": "08.02.04"
          },
          "05_conservation": {
            "name": "Water Conservation",
            "id": "08.02.05"
          }
        }
      },
      "03_food_preservation": {
        "name": "Food Preservation & Storage",
        "id": "08.03",
        "subcategories": {
          "01_canning": {
            "name": "Canning & Jarring",
            "id": "08.03.01"
          },
          "02_drying": {
            "name": "Drying & Dehydration",
            "id": "08.03.02"
          },
          "03_smoking": {
            "name": "Smoking Meats",
            "id": "08.03.03"
          },
          "04_salting": {
            "name": "Salting & Curing",
            "id": "08.03.04"
          },
          "05_fermentation": {
            "name": "Fermentation",
            "id": "08.03.05"
          }
        }
      },
      "04_shelter_construction": {
        "name": "Shelter Construction",
        "id": "08.04",
        "subcategories": {
          "01_temporary_shelters": {
            "name": "Temporary Shelters",
            "id": "08.04.01"
          },
          "02_permanent_structures": {
            "name": "Permanent Structures",
            "id": "08.04.02"
          },
          "03_insulation": {
            "name": "Insulation Techniques",
            "id": "08.04.03"
          },
          "04_underground": {
            "name": "Underground Shelters",
            "id": "08.04.04"
          },
          "05_materials": {
            "name": "Building Materials",
            "id": "08.04.05"
          }
        }
      },
      "05_fire_making": {
        "name": "Fire Making",
        "id": "08.05",
        "subcategories": {
          "01_friction_methods": {
            "name": "Friction Methods",
            "id": "08.05.01"
          },
          "02_spark_methods": {
            "name": "Spark Methods",
            "id": "08.05.02"
          },
          "03_fire_maintenance": {
            "name": "Fire Maintenance",
            "id": "08.05.03"
          },
          "04_fuel_types": {
            "name": "Fuel Types",
            "id": "08.05.04"
          },
          "05_fire_safety": {
            "name": "Fire Safety",
            "id": "08.05.05"
          }
        }
      },
      "06_navigation": {
        "name": "Navigation",
        "id": "08.06",
        "subcategories": {
          "01_celestial": {
            "name": "Celestial Navigation",
            "id": "08.06.01"
          },
          "02_compass": {
            "name": "Compass Usage",
            "id": "08.06.02"
          },
          "03_natural_signs": {
            "name": "Natural Navigation",
            "id": "08.06.03"
          },
          "04_map_reading": {
            "name": "Map Reading",
            "id": "08.06.04"
          },
          "05_gps_alternatives": {
            "name": "GPS Alternatives",
            "id": "08.06.05"
          }
        }
      },
      "07_communication": {
        "name": "Emergency Communication",
        "id": "08.07",
        "subcategories": {
          "01_radio": {
            "name": "Radio Communication",
            "id": "08.07.01"
          },
          "02_signaling": {
            "name": "Visual Signaling",
            "id": "08.07.02"
          },
          "03_morse_code": {
            "name": "Morse Code",
            "id": "08.07.03"
          },
          "04_emergency_codes": {
            "name": "Emergency Codes",
            "id": "08.07.04"
          },
          "05_mesh_networks": {
            "name": "Mesh Networks",
            "id": "08.07.05"
          }
        }
      },
      "08_defense": {
        "name": "Defense & Security",
        "id": "08.08"
      },
      "09_disaster_response": {
        "name": "Disaster Response",
        "id": "08.09"
      },
      "10_psychological_resilience": {
        "name": "Psychological Resilience",
        "id": "08.10"
      }
    }
  },
  "09_reference_documentation": {
    "name": "Reference & Documentation",
    "id": "09",
    "description": "Essential reference materials",
    "subcategories": {
      "01_encyclopedias": {
        "name": "Encyclopedias",
        "id": "09.01"
      },
      "02_dictionaries": {
        "name": "Dictionaries",
        "id": "09.02"
      },
      "03_manuals": {
        "name": "Technical Manuals",
        "id": "09.03"
      },
      "04_maps": {
        "name": "Maps & Atlases",
        "id": "09.04"
      },
      "05_standards": {
        "name": "Standards & Specifications",
        "id": "09.05"
      },
      "06_formulas": {
        "name": "Formulas & Tables",
        "id": "09.06"
      },
      "07_protocols": {
        "name": "Protocols & Procedures",
        "id": "09.07"
      },
      "08_blueprints": {
        "name": "Blueprints & Schematics",
        "id": "09.08"
      },
      "09_patents": {
        "name": "Patents",
        "id": "09.09"
      },
      "10_archives": {
        "name": "Historical Archives",
        "id": "09.10"
      }
    }
  },
  "10_cultural_preservation": {
    "name": "Cultural Preservation",
    "id": "10",
    "description": "Human culture and heritage",
    "subcategories": {
      "01_languages": {
        "name": "Languages",
        "id": "10.01",
        "subcategories": {
          "01_dictionaries": {
            "name": "Language Dictionaries",
            "id": "10.01.01"
          },
          "02_grammars": {
            "name": "Grammars",
            "id": "10.01.02"
          },
          "03_endangered_languages": {
            "name": "Endangered Languages",
            "id": "10.01.03"
          },
          "04_sign_languages": {
            "name": "Sign Languages",
            "id": "10.01.04"
          },
          "05_translation_resources": {
            "name": "Translation Resources",
            "id": "10.01.05"
          }
        }
      },
      "02_folklore": {
        "name": "Folklore & Mythology",
        "id": "10.02"
      },
      "03_traditions": {
        "name": "Traditions & Customs",
        "id": "10.03"
      },
      "04_recipes": {
        "name": "Traditional Recipes",
        "id": "10.04"
      },
      "05_music_notation": {
        "name": "Music & Songs",
        "id": "10.05"
      },
      "06_stories": {
        "name": "Stories & Narratives",
        "id": "10.06"
      },
      "07_games": {
        "name": "Games & Recreation",
        "id": "10.07"
      },
      "08_rituals": {
        "name": "Rituals & Ceremonies",
        "id": "10.08"
      },
      "09_art_techniques": {
        "name": "Traditional Art Techniques",
        "id": "10.09"
      },
      "10_oral_histories": {
        "name": "Oral Histories",
        "id": "10.10"
      }
    }
  },
  "11_digital_preservation": {
    "name": "Digital Preservation",
    "id": "11",
    "description": "Digital formats and preservation",
    "subcategories": {
      "01_file_formats": {
        "name": "File Formats",
        "id": "11.01",
        "subcategories": {
          "01_documents": {
            "name": "Document Formats",
            "id": "11.01.01"
          },
          "02_images": {
            "name": "Image Formats",
            "id": "11.01.02"
          },
          "03_audio": {
            "name": "Audio Formats",
            "id": "11.01.03"
          },
          "04_video": {
            "name": "Video Formats",
            "id": "11.01.04"
          },
          "05_archives": {
            "name": "Archive Formats",
            "id": "11.01.05"
          }
        }
      },
      "02_compression": {
        "name": "Compression Methods",
        "id": "11.02"
      },
      "03_encryption": {
        "name": "Encryption & Security",
        "id": "11.03"
      },
      "04_backup_strategies": {
        "name": "Backup Strategies",
        "id": "11.04"
      },
      "05_data_recovery": {
        "name": "Data Recovery",
        "id": "11.05"
      }
    }
  },
  "12_post_disaster_rebuilding": {
    "name": "Post-Disaster Rebuilding",
    "id": "12",
    "description": "Knowledge for rebuilding civilization",
    "subcategories": {
      "01_basic_infrastructure": {
        "name": "Basic Infrastructure",
        "id": "12.01",
        "subcategories": {
          "01_power_generation": {
            "name": "Basic Power Generation",
            "id": "12.01.01"
          },
          "02_water_systems": {
            "name": "Water Systems",
            "id": "12.01.02"
          },
          "03_sanitation": {
            "name": "Sanitation",
            "id": "12.01.03"
          },
          "04_communication": {
            "name": "Communication Networks",
            "id": "12.01.04"
          },
          "05_transportation": {
            "name": "Basic Transportation",
            "id": "12.01.05"
          }
        }
      },
      "02_tool_making": {
        "name": "Tool Making",
        "id": "12.02"
      },
      "03_basic_chemistry": {
        "name": "Essential Chemistry",
        "id": "12.03"
      },
      "04_basic_medicine": {
        "name": "Basic Medicine Production",
        "id": "12.04"
      },
      "05_community_building": {
        "name": "Community Organization",
        "id": "12.05"
      }
    }
  }
};
