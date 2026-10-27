document.addEventListener('DOMContentLoaded', function() {
    // Elements
    const runButton = document.getElementById('run-button');
    const statusIndicator = document.getElementById('status-indicator');
    const statusText = document.getElementById('status-text');
    const resultsPanel = document.getElementById('results-panel');
    const logContainer = document.getElementById('log-container');
    const reportContent = document.getElementById('report-content');
    const chartImage = document.getElementById('chart-image');
    const emailStatus = document.getElementById('email-status');
    const emailText = document.getElementById('email-text');
    const timestampElement = document.getElementById('timestamp');
    
    // Tab navigation
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');
    
    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            // Remove active class from all buttons and contents
            tabButtons.forEach(btn => btn.classList.remove('active'));
            tabContents.forEach(content => content.classList.remove('active'));
            
            // Add active class to clicked button and corresponding content
            button.classList.add('active');
            const tabId = button.getAttribute('data-tab');
            document.getElementById(`${tabId}-tab`).classList.add('active');
        });
    });
    
    // Run analysis
    runButton.addEventListener('click', function() {
        // Disable button during processing
        runButton.disabled = true;
        
        // Update status
        statusIndicator.className = 'status running';
        statusText.textContent = 'Running...';
        
        // Show results panel
        resultsPanel.style.display = 'block';
        
        // Clear previous results
        logContainer.innerHTML = '';
        reportContent.textContent = '';
        chartImage.src = '';
        emailStatus.className = 'email-status';
        emailText.textContent = 'Waiting to send email...';
        
        // Start the analysis
        fetch('/run-analysis', {
            method: 'POST'
        })
        .then(response => response.json())
        .then(data => {
            console.log('Analysis started:', data);
            // Start polling for updates
            pollStatus();
        })
        .catch(error => {
            console.error('Error starting analysis:', error);
            statusIndicator.className = 'status error';
            statusText.textContent = 'Error';
            runButton.disabled = false;
        });
    });
    
    // Poll for status updates
    function pollStatus() {
        fetch('/status')
            .then(response => response.json())
            .then(data => {
                // Update status
                statusIndicator.className = `status ${data.status}`;
                statusText.textContent = data.status.charAt(0).toUpperCase() + data.status.slice(1);
                
                // Update timestamp
                if (data.timestamp) {
                    timestampElement.textContent = `Started: ${data.timestamp}`;
                }
                
                // Update log
                logContainer.innerHTML = '';
                data.messages.forEach(message => {
                    const logLine = document.createElement('div');
                    logLine.textContent = message;
                    logContainer.appendChild(logLine);
                });
                
                // Auto-scroll log to bottom
                logContainer.scrollTop = logContainer.scrollHeight;
                
                // If completed, fetch report and chart
                if (data.status === 'completed') {
                    fetchReport();
                    fetchChart();
                    
                    // Update email status
                    if (data.email_sent) {
                        emailStatus.className = 'email-status sent';
                        emailText.textContent = 'Email sent successfully!';
                    }
                    
                    // Re-enable run button
                    runButton.disabled = false;
                } else if (data.status === 'error') {
                    // Handle error
                    emailStatus.className = 'email-status error';
                    emailText.textContent = 'Error sending email!';
                    runButton.disabled = false;
                } else {
                    // Continue polling if still running
                    setTimeout(pollStatus, 1000);
                }
            })
            .catch(error => {
                console.error('Error polling status:', error);
                setTimeout(pollStatus, 2000); // Retry with longer delay
            });
    }
    
    // Fetch report content
    function fetchReport() {
        fetch('/report')
            .then(response => response.json())
            .then(data => {
                reportContent.textContent = data.content;
            })
            .catch(error => {
                console.error('Error fetching report:', error);
                reportContent.textContent = 'Error loading report.';
            });
    }
    
    // Fetch chart image
    function fetchChart() {
        fetch('/chart')
            .then(response => response.json())
            .then(data => {
                if (data.filename) {
                    // Set the image source
                    chartImage.src = `/output/${data.filename}`;
                    chartImage.alt = 'Forest Classification Chart';
                }
            })
            .catch(error => {
                console.error('Error fetching chart:', error);
            });
    }
});
