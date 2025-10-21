// Smooth scrolling for navigation links
document.addEventListener('DOMContentLoaded', function() {
    // Smooth scrolling for anchor links
    const links = document.querySelectorAll('a[href^="#"]');
    
    links.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            
            const targetId = this.getAttribute('href');
            const targetSection = document.querySelector(targetId);
            
            if (targetSection) {
                const offsetTop = targetSection.offsetTop - 80; // Account for fixed navbar
                
                window.scrollTo({
                    top: offsetTop,
                    behavior: 'smooth'
                });
            }
        });
    });

    // Navbar background on scroll
    const navbar = document.querySelector('.navbar');
    
    window.addEventListener('scroll', function() {
        if (window.scrollY > 50) {
            navbar.style.background = 'rgba(10, 10, 10, 0.98)';
        } else {
            navbar.style.background = 'rgba(10, 10, 10, 0.95)';
        }
    });

    // Intersection Observer for animations
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };

    const observer = new IntersectionObserver(function(entries) {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('fade-in-up');
            }
        });
    }, observerOptions);

    // Observe elements for animation
    const animateElements = document.querySelectorAll('.innovation-card, .demo-card, .technical-card, .judge-card, .brain');
    animateElements.forEach(el => observer.observe(el));

    // Typing animation for code demo
    const codeLines = document.querySelectorAll('.code-line');
    let delay = 500;
    
    codeLines.forEach((line, index) => {
        setTimeout(() => {
            line.style.opacity = '1';
            typeWriter(line, line.textContent, 50);
        }, delay);
        delay += 2000;
    });

    // Network animation
    createNetworkAnimation();

    // Counter animation for stats
    animateCounters();

    // Interactive architecture diagram
    setupArchitectureDiagram();

    // Bot conversation simulation
    simulateBotConversation();
    
    // Architecture diagram toggle
    setupDiagramToggle();
    
    // Gallery filtering
    setupGalleryFilters();
});

// Typewriter effect
function typeWriter(element, text, speed) {
    element.textContent = '';
    let i = 0;
    
    function type() {
        if (i < text.length) {
            element.textContent += text.charAt(i);
            i++;
            setTimeout(type, speed);
        }
    }
    
    type();
}

// Network animation
function createNetworkAnimation() {
    const networkContainer = document.querySelector('.network-animation');
    
    // Create animated particles
    for (let i = 0; i < 20; i++) {
        const particle = document.createElement('div');
        particle.className = 'network-particle';
        particle.style.cssText = `
            position: absolute;
            width: 4px;
            height: 4px;
            background: var(--accent-cyan);
            border-radius: 50%;
            opacity: 0.6;
            animation: float ${3 + Math.random() * 4}s ease-in-out infinite;
            left: ${Math.random() * 100}%;
            top: ${Math.random() * 100}%;
            animation-delay: ${Math.random() * 2}s;
        `;
        networkContainer.appendChild(particle);
    }

    // Add CSS for particle animation
    const style = document.createElement('style');
    style.textContent = `
        @keyframes float {
            0%, 100% { transform: translateY(0px) translateX(0px); }
            25% { transform: translateY(-20px) translateX(10px); }
            50% { transform: translateY(-10px) translateX(-10px); }
            75% { transform: translateY(-30px) translateX(5px); }
        }
    `;
    document.head.appendChild(style);
}

// Counter animation
function animateCounters() {
    const counters = document.querySelectorAll('.stat-number');
    
    const observer = new IntersectionObserver(function(entries) {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const counter = entry.target;
                const target = counter.textContent;
                const isTime = target.includes('s');
                const isPercentage = target.includes('%');
                const isPlus = target.includes('+');
                
                let numericTarget;
                if (isTime) {
                    numericTarget = parseInt(target);
                } else if (isPercentage) {
                    numericTarget = parseFloat(target);
                } else if (isPlus) {
                    numericTarget = parseInt(target);
                } else {
                    numericTarget = parseFloat(target);
                }
                
                animateCounter(counter, 0, numericTarget, 2000, isTime, isPercentage, isPlus);
                observer.unobserve(counter);
            }
        });
    });
    
    counters.forEach(counter => observer.observe(counter));
}

function animateCounter(element, start, end, duration, isTime, isPercentage, isPlus) {
    const startTime = performance.now();
    
    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        
        const current = start + (end - start) * easeOutCubic(progress);
        
        let displayValue;
        if (isTime) {
            displayValue = Math.floor(current) + 's';
        } else if (isPercentage) {
            displayValue = current.toFixed(1) + '%';
        } else if (isPlus) {
            displayValue = Math.floor(current) + '+';
        } else {
            displayValue = current.toFixed(1);
        }
        
        element.textContent = displayValue;
        
        if (progress < 1) {
            requestAnimationFrame(update);
        }
    }
    
    requestAnimationFrame(update);
}

function easeOutCubic(t) {
    return 1 - Math.pow(1 - t, 3);
}

// Interactive architecture diagram
function setupArchitectureDiagram() {
    const brains = document.querySelectorAll('.brain');
    const services = document.querySelectorAll('.service-item');
    
    brains.forEach(brain => {
        brain.addEventListener('mouseenter', function() {
            this.style.transform = 'translateY(-10px) scale(1.05)';
            this.style.boxShadow = '0 20px 40px rgba(0, 212, 255, 0.3)';
        });
        
        brain.addEventListener('mouseleave', function() {
            this.style.transform = 'translateY(0) scale(1)';
            this.style.boxShadow = 'none';
        });
    });
    
    services.forEach(service => {
        service.addEventListener('mouseenter', function() {
            this.style.background = 'linear-gradient(135deg, var(--accent-cyan), var(--accent-purple))';
            this.style.color = 'white';
        });
        
        service.addEventListener('mouseleave', function() {
            this.style.background = 'var(--secondary-bg)';
            this.style.color = 'var(--text-primary)';
        });
    });
}

// Bot conversation simulation
function simulateBotConversation() {
    const messages = document.querySelectorAll('.message');
    
    // Hide all messages initially
    messages.forEach(message => {
        message.style.opacity = '0';
        message.style.transform = 'translateY(20px)';
    });
    
    // Show messages with delay
    messages.forEach((message, index) => {
        setTimeout(() => {
            message.style.transition = 'all 0.5s ease';
            message.style.opacity = '1';
            message.style.transform = 'translateY(0)';
        }, index * 1000);
    });
}

// Parallax effect for hero section
window.addEventListener('scroll', function() {
    const scrolled = window.pageYOffset;
    const parallax = document.querySelector('.hero-background');
    
    if (parallax) {
        const speed = scrolled * 0.5;
        parallax.style.transform = `translateY(${speed}px)`;
    }
});

// Interactive demo cards
document.addEventListener('DOMContentLoaded', function() {
    const demoCards = document.querySelectorAll('.demo-card');
    
    demoCards.forEach(card => {
        card.addEventListener('mouseenter', function() {
            const badge = this.querySelector('.demo-badge');
            if (badge) {
                badge.style.animation = 'pulse 1s infinite';
            }
        });
        
        card.addEventListener('mouseleave', function() {
            const badge = this.querySelector('.demo-badge');
            if (badge) {
                badge.style.animation = 'none';
            }
        });
    });
    
    // Add pulse animation
    const style = document.createElement('style');
    style.textContent = `
        @keyframes pulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.05); }
            100% { transform: scale(1); }
        }
    `;
    document.head.appendChild(style);
});

// Mobile menu toggle (if needed)
function toggleMobileMenu() {
    const navMenu = document.querySelector('.nav-menu');
    navMenu.classList.toggle('active');
}

// Scroll to top functionality
function scrollToTop() {
    window.scrollTo({
        top: 0,
        behavior: 'smooth'
    });
}

// Add scroll to top button
document.addEventListener('DOMContentLoaded', function() {
    const scrollButton = document.createElement('button');
    scrollButton.innerHTML = '<i class="fas fa-arrow-up"></i>';
    scrollButton.className = 'scroll-to-top';
    scrollButton.style.cssText = `
        position: fixed;
        bottom: 30px;
        right: 30px;
        width: 50px;
        height: 50px;
        border-radius: 50%;
        background: var(--gradient-primary);
        border: none;
        color: white;
        font-size: 1.2rem;
        cursor: pointer;
        opacity: 0;
        visibility: hidden;
        transition: all 0.3s ease;
        z-index: 1000;
    `;
    
    scrollButton.addEventListener('click', scrollToTop);
    document.body.appendChild(scrollButton);
    
    window.addEventListener('scroll', function() {
        if (window.scrollY > 500) {
            scrollButton.style.opacity = '1';
            scrollButton.style.visibility = 'visible';
        } else {
            scrollButton.style.opacity = '0';
            scrollButton.style.visibility = 'hidden';
        }
    });
});

// Form validation (if forms are added later)
function validateForm(form) {
    const inputs = form.querySelectorAll('input[required], textarea[required]');
    let isValid = true;
    
    inputs.forEach(input => {
        if (!input.value.trim()) {
            input.style.borderColor = '#ef4444';
            isValid = false;
        } else {
            input.style.borderColor = 'var(--border-color)';
        }
    });
    
    return isValid;
}

// Analytics tracking (placeholder)
function trackEvent(eventName, properties = {}) {
    // Placeholder for analytics tracking
    console.log('Event tracked:', eventName, properties);
    
    // Example: Google Analytics 4
    // gtag('event', eventName, properties);
    
    // Example: Custom analytics
    // analytics.track(eventName, properties);
}

// Track button clicks
document.addEventListener('click', function(e) {
    if (e.target.matches('.primary-button, .secondary-button, .cta-button')) {
        const buttonText = e.target.textContent.trim();
        trackEvent('button_click', {
            button_text: buttonText,
            page_section: e.target.closest('section')?.id || 'unknown'
        });
    }
});

// Performance monitoring
window.addEventListener('load', function() {
    // Track page load time
    const loadTime = performance.now();
    trackEvent('page_load', {
        load_time: Math.round(loadTime)
    });
});

// Error handling
window.addEventListener('error', function(e) {
    console.error('JavaScript error:', e.error);
    // Track errors for debugging
    trackEvent('javascript_error', {
        message: e.message,
        filename: e.filename,
        line: e.lineno
    });
});

// Lazy loading for images (if images are added)
function setupLazyLoading() {
    const images = document.querySelectorAll('img[data-src]');
    
    const imageObserver = new IntersectionObserver(function(entries) {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const img = entry.target;
                img.src = img.dataset.src;
                img.classList.remove('lazy');
                imageObserver.unobserve(img);
            }
        });
    });
    
    images.forEach(img => imageObserver.observe(img));
}

// Initialize lazy loading
document.addEventListener('DOMContentLoaded', setupLazyLoading);

// Architecture diagram toggle functionality
function setupDiagramToggle() {
    const toggleBtns = document.querySelectorAll('.toggle-btn');
    const diagrams = document.querySelectorAll('.arch-diagram');
    
    toggleBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const diagramType = this.dataset.diagram;
            
            // Update button states
            toggleBtns.forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            
            // Update diagram visibility
            diagrams.forEach(diagram => {
                diagram.classList.remove('active');
            });
            
            const targetDiagram = document.getElementById(`${diagramType}-diagram`);
            if (targetDiagram) {
                targetDiagram.classList.add('active');
            }
        });
    });
}

// Gallery filtering functionality
function setupGalleryFilters() {
    const filterBtns = document.querySelectorAll('.filter-btn');
    const galleryItems = document.querySelectorAll('.gallery-item');
    
    filterBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const filter = this.dataset.filter;
            
            // Update button states
            filterBtns.forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            
            // Filter gallery items
            galleryItems.forEach(item => {
                if (filter === 'all' || item.dataset.category === filter) {
                    item.style.display = 'block';
                    item.style.animation = 'fadeInUp 0.5s ease';
                } else {
                    item.style.display = 'none';
                }
            });
        });
    });
}

// Service Worker registration (for PWA features)
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        navigator.serviceWorker.register('/sw.js')
            .then(function(registration) {
                console.log('ServiceWorker registration successful');
            })
            .catch(function(err) {
                console.log('ServiceWorker registration failed');
            });
    });
}